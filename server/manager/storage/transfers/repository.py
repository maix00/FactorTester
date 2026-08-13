"""Transactional SQLite authority for cross-node transfer attempts."""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

from server.manager.storage.transfers.database import TransferDatabase
from server.manager.storage.transfers.outbox import (
    acknowledge_message,
    claim_messages,
)
from server.manager.storage.transfers.records import (
    normalize_new,
    required,
    same_request,
    transfer_record,
)
from server.manager.transfers.models import (
    NewTransfer,
    OutboxMessage,
    TransferRecord,
    TransferStatus,
)
from server.manager.transfers.state_machine import require_transfer_transition


class TransferStore(TransferDatabase):
    """Persist a request and every delivery intent in one local transaction."""

    def __init__(self, path: str | Path, *, server_id: str) -> None:
        super().__init__(path, server_id=server_id)

    def create(
        self,
        request: NewTransfer,
        *,
        dispatch_to: str,
        now: float | None = None,
    ) -> TransferRecord:
        current = time.time() if now is None else float(now)
        normalized = normalize_new(request, now=current)
        target_manager_id = required(dispatch_to, field="dispatch_to")
        transfer_id = secrets.token_hex(16)
        outbox_id = secrets.token_hex(16)
        payload = {
            "schema_version": 1,
            "transfer_id": transfer_id,
            "operation": normalized.operation.value,
            "principal": normalized.principal,
            "request_owner_manager_id": normalized.request_owner_manager_id,
            "relay_owner_manager_id": normalized.relay_owner_manager_id,
            "source_server_id": normalized.source_server_id,
            "destination_server_id": normalized.destination_server_id,
            "storage_server_id": normalized.storage_server_id,
            "job_id": normalized.job_id,
            "artifact_name": normalized.artifact_name,
            "expected_size": normalized.expected_size,
            "expected_sha256": normalized.expected_sha256,
            "expires_at": normalized.expires_at,
        }
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
                    request_owner_manager_id, relay_owner_manager_id,
                    source_server_id, destination_server_id, storage_server_id,
                    job_id, artifact_name, expected_size, expected_sha256,
                    created_at, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transfer_id, normalized.idempotency_key,
                    normalized.operation.value, TransferStatus.CREATED.value,
                    normalized.principal, normalized.request_owner_manager_id,
                    normalized.relay_owner_manager_id,
                    normalized.source_server_id,
                    normalized.destination_server_id,
                    normalized.storage_server_id, normalized.job_id,
                    normalized.artifact_name, normalized.expected_size,
                    normalized.expected_sha256, current, current,
                    normalized.expires_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO transfer_outbox(
                    outbox_id, transfer_id, event_type, target_manager_id,
                    payload_json, created_at
                ) VALUES (?, ?, 'transfer.requested', ?, ?, ?)
                """,
                (
                    outbox_id, transfer_id, target_manager_id,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    current,
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

    def claim_outbox(
        self,
        *,
        claimant: str,
        limit: int = 100,
        lease_seconds: float = 30.0,
        now: float | None = None,
    ) -> list[OutboxMessage]:
        owner = required(claimant, field="claimant")
        batch_size = max(1, min(500, int(limit)))
        current = time.time() if now is None else float(now)
        lease_expires_at = current + max(1.0, float(lease_seconds))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return claim_messages(
                connection,
                claimant=owner,
                limit=batch_size,
                now=current,
                lease_expires_at=lease_expires_at,
            )

    def acknowledge_outbox(
        self,
        outbox_id: str,
        *,
        claimant: str,
        now: float | None = None,
    ) -> None:
        identifier = required(outbox_id, field="outbox_id")
        owner = required(claimant, field="claimant")
        current = time.time() if now is None else float(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            acknowledge_message(
                connection,
                outbox_id=identifier,
                claimant=owner,
                now=current,
            )
