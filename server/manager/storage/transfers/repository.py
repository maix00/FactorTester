"""Transactional SQLite authority for cross-node transfer attempts."""

from __future__ import annotations

import secrets
import time
from pathlib import Path

from server.manager.storage.transfers.database import TransferDatabase
from server.manager.storage.transfers.records import (
    normalize_new,
    required,
    same_request,
    transfer_record,
)
from server.manager.transfers.models import (
    NewTransfer,
    TransferRecord,
    TransferStatus,
)
from server.manager.transfers.state_machine import require_transfer_transition


class TransferStore(TransferDatabase):
    """Persist requests owned by this Manager in its local SQLite database."""

    def __init__(self, path: str | Path, *, server_id: str) -> None:
        super().__init__(path, server_id=server_id)

    def create(
        self,
        request: NewTransfer,
        *,
        now: float | None = None,
    ) -> TransferRecord:
        current = time.time() if now is None else float(now)
        normalized = normalize_new(request, now=current)
        transfer_id = secrets.token_hex(16)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM transfer_requests WHERE idempotency_key=?",
                (normalized.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if not same_request(existing, normalized):
                    raise ValueError(
                        "transfer idempotency key conflicts with an existing request"
                    )
                return transfer_record(existing)
            connection.execute(
                """
                INSERT INTO transfer_requests(
                    transfer_id, idempotency_key, operation, status, principal,
                    request_owner_manager_id,
                    source_server_id, destination_server_id, storage_server_id,
                    job_id, artifact_name, expected_size, expected_sha256,
                    content_type, created_at, updated_at, expires_at,
                    object_kind, object_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transfer_id, normalized.idempotency_key,
                    normalized.operation.value, TransferStatus.CREATED.value,
                    normalized.principal, normalized.request_owner_manager_id,
                    normalized.source_server_id,
                    normalized.destination_server_id,
                    normalized.storage_server_id, normalized.job_id,
                    normalized.artifact_name, normalized.expected_size,
                    normalized.expected_sha256, normalized.content_type,
                    current, current, normalized.expires_at,
                    normalized.object_kind,
                    normalized.object_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM transfer_requests WHERE transfer_id=?",
                (transfer_id,),
            ).fetchone()
        if row is None:  # pragma: no cover - protected by the transaction
            raise RuntimeError("transfer request was not persisted")
        return transfer_record(row)

    def require(self, transfer_id: str) -> TransferRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM transfer_requests WHERE transfer_id=?",
                (required(transfer_id, field="transfer_id"),),
            ).fetchone()
        if row is None:
            raise KeyError("transfer request not found")
        return transfer_record(row)

    def transition(
        self,
        transfer_id: str,
        target: TransferStatus | str,
        *,
        expected: TransferStatus | str | None = None,
        now: float | None = None,
    ) -> TransferRecord:
        identifier = required(transfer_id, field="transfer_id")
        selected = TransferStatus(target)
        expected_status = TransferStatus(expected) if expected is not None else None
        current_time = time.time() if now is None else float(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM transfer_requests WHERE transfer_id=?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise KeyError("transfer request not found")
            current = TransferStatus(str(row["status"]))
            # Delivery is at-least-once. Replaying a command that already
            # reached its target is success even when the caller's expected
            # predecessor is now stale.
            if current is selected:
                return transfer_record(row)
            if expected_status is not None and current is not expected_status:
                raise RuntimeError(
                    "transfer state changed: "
                    f"expected {expected_status.value}, found {current.value}"
                )
            require_transfer_transition(current, selected)
            connection.execute(
                """
                UPDATE transfer_requests SET status=?, updated_at=?
                WHERE transfer_id=?
                """,
                (selected.value, current_time, identifier),
            )
            updated = connection.execute(
                "SELECT * FROM transfer_requests WHERE transfer_id=?",
                (identifier,),
            ).fetchone()
        if updated is None:  # pragma: no cover - protected by transaction
            raise RuntimeError("transfer request disappeared")
        return transfer_record(updated)
