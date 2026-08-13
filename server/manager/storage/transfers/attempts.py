"""SQLite Adapter for fixed-topology Transfer Attempts."""

from __future__ import annotations

import secrets
import time
from pathlib import Path

from server.manager.storage.transfers.attempt_records import (
    attempt_record,
    normalize_attempt,
    same_attempt,
)
from server.manager.storage.transfers.database import TransferDatabase
from server.manager.storage.transfers.records import required
from server.manager.transfers.models import (
    AttemptStatus,
    NewTransferAttempt,
    TransferAttemptRecord,
    TransferStatus,
)
from server.manager.transfers.state_machine import (
    TERMINAL_ATTEMPT_STATUSES,
    require_attempt_transition,
)


class TransferAttemptStore(TransferDatabase):
    def __init__(self, path: str | Path, *, server_id: str) -> None:
        super().__init__(path, server_id=server_id)

    def begin(
        self,
        value: NewTransferAttempt,
        *,
        now: float | None = None,
    ) -> TransferAttemptRecord:
        current = time.time() if now is None else float(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            parent = connection.execute(
                "SELECT * FROM transfer_requests WHERE transfer_id=?",
                (required(value.transfer_id, field="transfer_id"),),
            ).fetchone()
            if parent is None:
                raise KeyError("transfer request not found")
            normalized = normalize_attempt(
                value, expected_size=int(parent["expected_size"]), now=current,
            )
            existing = connection.execute(
                "SELECT * FROM transfer_attempts WHERE attempt_key=?",
                (normalized.attempt_key,),
            ).fetchone()
            if existing is not None:
                if not same_attempt(existing, normalized):
                    raise ValueError("transfer attempt key conflicts")
                return attempt_record(existing)
            if TransferStatus(str(parent["status"])) is not TransferStatus.PLANNED:
                raise RuntimeError("transfer must be planned before an attempt")
            active = connection.execute(
                """
                SELECT 1 FROM transfer_attempts
                WHERE transfer_id=? AND status NOT IN (?, ?, ?, ?)
                LIMIT 1
                """,
                (
                    normalized.transfer_id,
                    *(status.value for status in TERMINAL_ATTEMPT_STATUSES),
                ),
            ).fetchone()
            if active is not None:
                raise RuntimeError("transfer already has an active attempt")
            ordinal = int(parent["attempt"]) + 1
            attempt_id = secrets.token_hex(16)
            connection.execute(
                """
                INSERT INTO transfer_attempts(
                    attempt_id, attempt_key, transfer_id, ordinal, mode, status,
                    relay_owner_manager_id, connection_owner_manager_id,
                    source_server_id, destination_server_id, resume_offset,
                    expected_size, expected_sha256, created_at, updated_at,
                    expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id, normalized.attempt_key,
                    normalized.transfer_id, ordinal, normalized.mode.value,
                    AttemptStatus.PLANNED.value,
                    normalized.relay_owner_manager_id,
                    normalized.connection_owner_manager_id,
                    normalized.source_server_id,
                    normalized.destination_server_id,
                    normalized.resume_offset, int(parent["expected_size"]),
                    str(parent["expected_sha256"]), current, current,
                    normalized.expires_at,
                ),
            )
            connection.execute(
                "UPDATE transfer_requests SET attempt=?, updated_at=? "
                "WHERE transfer_id=?",
                (ordinal, current, normalized.transfer_id),
            )
            row = connection.execute(
                "SELECT * FROM transfer_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
        if row is None:  # pragma: no cover - transaction invariant
            raise RuntimeError("transfer attempt was not persisted")
        return attempt_record(row)

    def require(self, attempt_id: str) -> TransferAttemptRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM transfer_attempts WHERE attempt_id=?",
                (required(attempt_id, field="attempt_id"),),
            ).fetchone()
        if row is None:
            raise KeyError("transfer attempt not found")
        return attempt_record(row)

    def transition(
        self,
        attempt_id: str,
        target: AttemptStatus | str,
        *,
        now: float | None = None,
        error: str = "",
    ) -> TransferAttemptRecord:
        identifier = required(attempt_id, field="attempt_id")
        selected = AttemptStatus(target)
        current_time = time.time() if now is None else float(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM transfer_attempts WHERE attempt_id=?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise KeyError("transfer attempt not found")
            current = AttemptStatus(str(row["status"]))
            if current is selected:
                return attempt_record(row)
            require_attempt_transition(current, selected)
            connection.execute(
                "UPDATE transfer_attempts SET status=?, updated_at=?, "
                "last_error=? WHERE attempt_id=?",
                (selected.value, current_time, str(error or ""), identifier),
            )
            updated = connection.execute(
                "SELECT * FROM transfer_attempts WHERE attempt_id=?",
                (identifier,),
            ).fetchone()
        return attempt_record(updated)
