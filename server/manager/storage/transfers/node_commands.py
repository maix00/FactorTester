"""Durable public-Manager command queue for one outbound node channel."""

from __future__ import annotations

import secrets
import time
from pathlib import Path

from server.manager.storage.transfers.database import TransferDatabase
from server.manager.storage.transfers.node_command_records import (
    node_command_record,
    normalize_node_command,
    same_node_command,
)
from server.manager.storage.transfers.records import required
from server.manager.transfers.node_models import NewNodeCommand, NodeCommandRecord


class NodeCommandQueue(TransferDatabase):
    def __init__(self, path: str | Path, *, server_id: str) -> None:
        super().__init__(path, server_id=server_id)

    def enqueue(
        self,
        value: NewNodeCommand,
        *,
        now: float | None = None,
    ) -> NodeCommandRecord:
        current = time.time() if now is None else float(now)
        command, payload_json, payload_hash = normalize_node_command(
            value, now=current,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM transfer_node_commands WHERE idempotency_key=?",
                (command.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if not same_node_command(existing, command, payload_hash):
                    raise ValueError("node command idempotency key conflicts")
                return node_command_record(existing)
            sequence_row = connection.execute(
                "SELECT last_sequence FROM transfer_node_command_sequences "
                "WHERE target_server_id=?",
                (command.target_server_id,),
            ).fetchone()
            sequence = int(sequence_row["last_sequence"]) + 1 \
                if sequence_row is not None else 1
            connection.execute(
                """
                INSERT INTO transfer_node_command_sequences(
                    target_server_id, last_sequence
                ) VALUES (?, ?)
                ON CONFLICT(target_server_id)
                DO UPDATE SET last_sequence=excluded.last_sequence
                """,
                (command.target_server_id, sequence),
            )
            command_id = secrets.token_hex(16)
            connection.execute(
                """
                INSERT INTO transfer_node_commands(
                    command_id, idempotency_key, transfer_id, attempt_id,
                    command_type, target_server_id, sequence, payload_json,
                    payload_hash, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command_id, command.idempotency_key, command.transfer_id,
                    command.attempt_id, command.command_type,
                    command.target_server_id, sequence, payload_json,
                    payload_hash, current, command.expires_at,
                ),
            )
            stored = connection.execute(
                "SELECT * FROM transfer_node_commands WHERE command_id=?",
                (command_id,),
            ).fetchone()
        return node_command_record(stored)

    def pending(
        self,
        *,
        node_id: str,
        after_sequence: int = 0,
        limit: int = 100,
        include_replay: bool = True,
        now: float | None = None,
    ) -> list[NodeCommandRecord]:
        current = time.time() if now is None else float(now)
        with self._connect() as connection:
            cursor = max(0, int(after_sequence))
            replay_clause = "" if include_replay else "AND sequence>?"
            parameters: tuple[object, ...] = (
                required(node_id, field="node_id"), current,
                *((cursor,) if not include_replay else ()),
                cursor,
                max(1, min(500, int(limit))),
            )
            rows = connection.execute(
                f"""
                SELECT * FROM transfer_node_commands
                WHERE target_server_id=? AND acknowledged_at IS NULL
                  AND expires_at>? {replay_clause}
                ORDER BY
                  CASE WHEN sequence>? THEN 0 ELSE 1 END,
                  sequence
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [node_command_record(row) for row in rows]

    def acknowledge(
        self,
        command_id: str,
        *,
        node_id: str,
        now: float | None = None,
    ) -> None:
        current = time.time() if now is None else float(now)
        identifier = required(command_id, field="command_id")
        target = required(node_id, field="node_id")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT target_server_id FROM transfer_node_commands "
                "WHERE command_id=?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise KeyError("node command not found")
            if str(row["target_server_id"]) != target:
                raise PermissionError("node command target mismatch")
            connection.execute(
                "UPDATE transfer_node_commands "
                "SET acknowledged_at=COALESCE(acknowledged_at, ?) "
                "WHERE command_id=?",
                (current, identifier),
            )
