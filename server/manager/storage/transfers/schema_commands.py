"""Node-local durable command inbox used by SSE replay and fallback polling."""

from __future__ import annotations

import sqlite3


def ensure_command_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS transfer_inbox (
            command_id TEXT PRIMARY KEY,
            transfer_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            command_type TEXT NOT NULL,
            target_server_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            delivery_attempt INTEGER NOT NULL DEFAULT 0,
            lease_owner TEXT NOT NULL DEFAULT '',
            lease_expires_at REAL,
            received_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            completed_at REAL,
            last_error TEXT NOT NULL DEFAULT '',
            UNIQUE (target_server_id, sequence),
            CHECK (sequence >= 0),
            CHECK (delivery_attempt >= 0),
            CHECK (status IN ('pending', 'leased', 'completed', 'failed'))
        );

        CREATE INDEX IF NOT EXISTS transfer_inbox_pending
            ON transfer_inbox(target_server_id, status, lease_expires_at, sequence);
        """
    )

