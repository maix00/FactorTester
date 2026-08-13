"""Import immutable Transfer/Attempt context onto an involved peer node."""

from __future__ import annotations

import time
from pathlib import Path

from server.manager.storage.transfers.attempt_records import attempt_record
from server.manager.storage.transfers.database import TransferDatabase
from server.manager.storage.transfers.records import transfer_record
from server.manager.transfers.models import (
    AttemptRouteSnapshot,
    TransferAttemptRecord,
    TransferOperation,
    TransferRecord,
)


class TransferReplicaStore(TransferDatabase):
    def __init__(self, path: str | Path, *, server_id: str) -> None:
        super().__init__(path, server_id=server_id)

    def import_context(
        self,
        transfer: TransferRecord,
        attempt: TransferAttemptRecord,
        *,
        now: float | None = None,
    ) -> tuple[TransferRecord, TransferAttemptRecord]:
        current = time.time() if now is None else float(now)
        if transfer.transfer_id != attempt.transfer_id:
            raise ValueError("transfer replica Attempt belongs to another request")
        context_owner = (
            transfer.source_server_id
            if transfer.operation is TransferOperation.DOWNLOAD
            else transfer.destination_server_id
        )
        if self.server_id != context_owner:
            raise PermissionError("transfer replica targets another storage server")
        if min(transfer.expires_at, attempt.expires_at) <= current:
            raise ValueError("transfer replica context has expired")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_transfer = connection.execute(
                "SELECT * FROM transfer_requests WHERE transfer_id=?",
                (transfer.transfer_id,),
            ).fetchone()
            if existing_transfer is None:
                self._insert_transfer(connection, transfer)
            elif not _same_transfer(existing_transfer, transfer):
                raise ValueError("transfer replica conflicts with local request")
            existing_attempt = connection.execute(
                "SELECT * FROM transfer_attempts WHERE attempt_id=?",
                (attempt.attempt_id,),
            ).fetchone()
            if existing_attempt is None:
                self._insert_attempt(connection, attempt)
            elif not _same_attempt(existing_attempt, attempt):
                raise ValueError("transfer replica conflicts with local Attempt")
            stored_transfer = connection.execute(
                "SELECT * FROM transfer_requests WHERE transfer_id=?",
                (transfer.transfer_id,),
            ).fetchone()
            stored_attempt = connection.execute(
                "SELECT * FROM transfer_attempts WHERE attempt_id=?",
                (attempt.attempt_id,),
            ).fetchone()
        return transfer_record(stored_transfer), attempt_record(stored_attempt)

    def require_context(
        self, attempt_id: str,
    ) -> tuple[TransferRecord, TransferAttemptRecord]:
        with self._connect() as connection:
            attempt_row = connection.execute(
                "SELECT * FROM transfer_attempts WHERE attempt_id=?",
                (str(attempt_id),),
            ).fetchone()
            if attempt_row is None:
                raise KeyError("transfer Attempt replica not found")
            transfer_row = connection.execute(
                "SELECT * FROM transfer_requests WHERE transfer_id=?",
                (str(attempt_row["transfer_id"]),),
            ).fetchone()
        return transfer_record(transfer_row), attempt_record(attempt_row)

    @staticmethod
    def _insert_transfer(connection, value: TransferRecord) -> None:
        connection.execute(
            """
            INSERT INTO transfer_requests(
                transfer_id, idempotency_key, operation, status, principal,
                request_owner_manager_id, relay_owner_manager_id,
                connection_owner_manager_id, source_server_id,
                destination_server_id, storage_server_id, job_id,
                artifact_name, expected_size, expected_sha256, attempt,
                created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                value.transfer_id, value.idempotency_key,
                value.operation.value, value.status.value, value.principal,
                value.request_owner_manager_id, value.relay_owner_manager_id,
                value.connection_owner_manager_id, value.source_server_id,
                value.destination_server_id, value.storage_server_id,
                value.job_id, value.artifact_name, value.expected_size,
                value.expected_sha256, value.attempt, value.created_at,
                value.updated_at, value.expires_at,
            ),
        )

    @staticmethod
    def _insert_attempt(
        connection, value: TransferAttemptRecord,
    ) -> None:
        connection.execute(
            """
            INSERT INTO transfer_attempts(
                attempt_id, attempt_key, transfer_id, ordinal, mode, status,
                relay_owner_manager_id, connection_owner_manager_id,
                source_server_id, destination_server_id, resume_offset,
                relay_data_endpoint, source_data_endpoint,
                source_control_endpoint, destination_data_endpoint,
                destination_control_endpoint,
                request_owner_control_endpoint,
                connection_owner_control_endpoint,
                expected_size, expected_sha256, created_at, updated_at,
                expires_at, last_error
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            (
                value.attempt_id, value.attempt_key, value.transfer_id,
                value.ordinal, value.mode.value, value.status.value,
                value.relay_owner_manager_id,
                value.connection_owner_manager_id, value.source_server_id,
                value.destination_server_id, value.resume_offset,
                value.routes.relay_data_endpoint,
                value.routes.source_data_endpoint,
                value.routes.source_control_endpoint,
                value.routes.destination_data_endpoint,
                value.routes.destination_control_endpoint,
                value.routes.request_owner_control_endpoint,
                value.routes.connection_owner_control_endpoint,
                value.expected_size, value.expected_sha256,
                value.created_at, value.updated_at, value.expires_at,
                value.last_error,
            ),
        )


def _same_transfer(row, value: TransferRecord) -> bool:
    text_fields = (
        "idempotency_key",
        "operation", "principal", "request_owner_manager_id",
        "relay_owner_manager_id", "connection_owner_manager_id",
        "source_server_id", "destination_server_id", "storage_server_id",
        "job_id", "artifact_name", "expected_sha256",
    )
    return (
        all(
            str(row[field]) == _record_text(value, field)
            for field in text_fields
        )
        and int(row["expected_size"]) == value.expected_size
        and float(row["expires_at"]) == value.expires_at
    )


def _record_text(value: TransferRecord, field: str) -> str:
    selected = getattr(value, field)
    return str(selected.value if field == "operation" else selected)


def _same_attempt(row, value: TransferAttemptRecord) -> bool:
    return (
        str(row["transfer_id"]) == value.transfer_id
        and int(row["ordinal"]) == value.ordinal
        and str(row["mode"]) == value.mode.value
        and str(row["relay_owner_manager_id"]) == value.relay_owner_manager_id
        and str(row["connection_owner_manager_id"])
        == value.connection_owner_manager_id
        and str(row["source_server_id"]) == value.source_server_id
        and str(row["destination_server_id"]) == value.destination_server_id
        and all(
            str(row[field]) == str(getattr(value.routes, field))
            for field in AttemptRouteSnapshot.__dataclass_fields__
        )
        and int(row["resume_offset"]) == value.resume_offset
        and int(row["expected_size"]) == value.expected_size
        and str(row["expected_sha256"]) == value.expected_sha256
        and float(row["expires_at"]) == value.expires_at
    )
