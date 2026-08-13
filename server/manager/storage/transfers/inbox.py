"""Durable node command inbox behind SSE delivery and long-poll fallback."""

from __future__ import annotations

import time
from pathlib import Path

from server.manager.storage.transfers.command_records import (
    command_record,
    normalize_command,
    same_command,
)
from server.manager.storage.transfers.database import TransferDatabase
from server.manager.storage.transfers.records import required
from server.manager.transfers.models import NewTransferCommand, TransferCommandRecord


class TransferInboxStore(TransferDatabase):
    def __init__(self, path: str | Path, *, server_id: str) -> None:
        super().__init__(path, server_id=server_id)

    def receive(
        self,
        command: NewTransferCommand,
        *,
        now: float | None = None,
    ) -> TransferCommandRecord:
        current = time.time() if now is None else float(now)
        normalized, payload_json, payload_hash = normalize_command(
            command, server_id=self.server_id, now=current,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM transfer_inbox WHERE command_id=?",
                (normalized.command_id,),
            ).fetchone()
            if row is not None:
                if not same_command(row, normalized, payload_hash):
                    raise ValueError("transfer command id conflicts")
                return command_record(row)
            sequence_row = connection.execute(
                """
                SELECT command_id FROM transfer_inbox
                WHERE target_server_id=? AND sequence=?
                """,
                (normalized.target_server_id, normalized.sequence),
            ).fetchone()
            if sequence_row is not None:
                raise ValueError("transfer command sequence conflicts")
            connection.execute(
                """
                INSERT INTO transfer_inbox(
                    command_id, transfer_id, attempt_id, command_type,
                    target_server_id, sequence, payload_json, payload_hash,
                    received_at, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized.command_id, normalized.transfer_id,
                    normalized.attempt_id, normalized.command_type,
                    normalized.target_server_id, normalized.sequence,
                    payload_json, payload_hash, current, current,
                    normalized.expires_at,
                ),
            )
            stored = connection.execute(
                "SELECT * FROM transfer_inbox WHERE command_id=?",
                (normalized.command_id,),
            ).fetchone()
        return command_record(stored)

    def claim(
        self,
        *,
        claimant: str,
        limit: int = 100,
        lease_seconds: float = 30.0,
        now: float | None = None,
    ) -> list[TransferCommandRecord]:
        owner = required(claimant, field="claimant")
        current = time.time() if now is None else float(now)
        lease_expiry = current + max(1.0, float(lease_seconds))
        batch_size = max(1, min(500, int(limit)))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM transfer_inbox
                WHERE expires_at>?
                  AND (status='pending' OR (
                      status='leased' AND lease_expires_at<=?
                  ))
                ORDER BY sequence, received_at LIMIT ?
                """,
                (current, current, batch_size),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE transfer_inbox
                    SET status='leased', lease_owner=?, lease_expires_at=?,
                        delivery_attempt=delivery_attempt+1, updated_at=?
                    WHERE command_id=?
                    """,
                    (owner, lease_expiry, current, str(row["command_id"])),
                )
            claimed = connection.execute(
                "SELECT * FROM transfer_inbox WHERE lease_owner=? "
                "AND lease_expires_at=? ORDER BY sequence",
                (owner, lease_expiry),
            ).fetchall()
        return [command_record(row) for row in claimed]

    def complete(
        self,
        command_id: str,
        *,
        claimant: str,
        now: float | None = None,
    ) -> None:
        identifier = required(command_id, field="command_id")
        owner = required(claimant, field="claimant")
        current = time.time() if now is None else float(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, lease_owner FROM transfer_inbox WHERE command_id=?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise KeyError("transfer command not found")
            if str(row["lease_owner"]) != owner:
                raise RuntimeError("transfer inbox lease owner changed")
            if str(row["status"]) == "completed":
                return
            connection.execute(
                """
                UPDATE transfer_inbox SET status='completed', completed_at=?,
                    updated_at=?, lease_expires_at=NULL, last_error=''
                WHERE command_id=?
                """,
                (current, current, identifier),
            )

