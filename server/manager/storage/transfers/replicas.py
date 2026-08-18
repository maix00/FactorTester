"""Import immutable Transfer/Attempt context onto its storage peer."""

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
        owner = (
            transfer.source_server_id
            if transfer.operation is TransferOperation.DOWNLOAD
            else transfer.destination_server_id
        )
        if self.server_id != owner:
            raise PermissionError("transfer replica targets another storage server")
        if min(transfer.expires_at, attempt.expires_at) <= current:
            raise ValueError("transfer replica context has expired")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            stored_transfer = connection.execute(
                "SELECT * FROM transfer_requests WHERE transfer_id=?",
                (transfer.transfer_id,),
            ).fetchone()
            if stored_transfer is None:
                _insert_transfer(connection, transfer)
            elif not _same_transfer(stored_transfer, transfer):
                raise ValueError("transfer replica conflicts with local request")
            stored_attempt = connection.execute(
                "SELECT * FROM transfer_attempts WHERE attempt_id=?",
                (attempt.attempt_id,),
            ).fetchone()
            if stored_attempt is None:
                _insert_attempt(connection, attempt)
            elif not _same_attempt(stored_attempt, attempt):
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
            attempt = connection.execute(
                "SELECT * FROM transfer_attempts WHERE attempt_id=?",
                (str(attempt_id),),
            ).fetchone()
            if attempt is None:
                raise KeyError("transfer Attempt replica not found")
            transfer = connection.execute(
                "SELECT * FROM transfer_requests WHERE transfer_id=?",
                (str(attempt["transfer_id"]),),
            ).fetchone()
        return transfer_record(transfer), attempt_record(attempt)


def _insert_transfer(connection, value: TransferRecord) -> None:
    connection.execute(
        """
        INSERT INTO transfer_requests(
            transfer_id, idempotency_key, operation, status, principal,
            request_owner_manager_id, source_server_id, destination_server_id,
            storage_server_id, job_id, artifact_name, expected_size,
            expected_sha256, content_type, attempt, created_at, updated_at,
            expires_at, object_kind, object_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            value.transfer_id, value.idempotency_key, value.operation.value,
            value.status.value, value.principal, value.request_owner_manager_id,
            value.source_server_id, value.destination_server_id,
            value.storage_server_id, value.job_id, value.artifact_name,
            value.expected_size, value.expected_sha256, value.content_type,
            value.attempt, value.created_at, value.updated_at,
            value.expires_at,
            value.object_kind, value.object_id,
        ),
    )


def _insert_attempt(connection, value: TransferAttemptRecord) -> None:
    route_values = tuple(
        getattr(value.routes, field)
        for field in AttemptRouteSnapshot.__dataclass_fields__
    )
    connection.execute(
        """
        INSERT INTO transfer_attempts(
            attempt_id, attempt_key, transfer_id, ordinal, mode, status,
            request_owner_manager_id, source_server_id, destination_server_id,
            client_data_endpoint, source_peer_data_endpoint,
            source_peer_control_endpoint, destination_peer_data_endpoint,
            destination_peer_control_endpoint, resume_offset, expected_size,
            expected_sha256, created_at, updated_at, expires_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            value.attempt_id, value.attempt_key, value.transfer_id,
            value.ordinal, value.mode.value, value.status.value,
            value.request_owner_manager_id, value.source_server_id,
            value.destination_server_id, *route_values, value.resume_offset,
            value.expected_size, value.expected_sha256, value.created_at,
            value.updated_at, value.expires_at, value.last_error,
        ),
    )


def _same_transfer(row, value: TransferRecord) -> bool:
    fields = (
        "idempotency_key", "principal", "request_owner_manager_id",
        "source_server_id", "destination_server_id", "storage_server_id",
        "job_id", "artifact_name", "expected_sha256", "content_type",
    )
    return (
        str(row["operation"]) == value.operation.value
        and all(str(row[field]) == str(getattr(value, field)) for field in fields)
        and int(row["expected_size"]) == value.expected_size
        and float(row["expires_at"]) == value.expires_at
        and str(row["object_kind"] or "job_artifact") == value.object_kind
        and str(row["object_id"] or "") == value.object_id
    )


def _same_attempt(row, value: TransferAttemptRecord) -> bool:
    return (
        str(row["transfer_id"]) == value.transfer_id
        and int(row["ordinal"]) == value.ordinal
        and str(row["mode"]) == value.mode.value
        and str(row["request_owner_manager_id"]) == value.request_owner_manager_id
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
