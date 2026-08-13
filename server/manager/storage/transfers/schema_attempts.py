"""Immutable topology and mutable lifecycle for transfer attempts."""

from __future__ import annotations

import sqlite3


def ensure_attempt_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS transfer_attempts (
            attempt_id TEXT PRIMARY KEY,
            attempt_key TEXT NOT NULL UNIQUE,
            transfer_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            relay_owner_manager_id TEXT NOT NULL,
            connection_owner_manager_id TEXT NOT NULL DEFAULT '',
            source_server_id TEXT NOT NULL,
            destination_server_id TEXT NOT NULL,
            relay_data_endpoint TEXT NOT NULL DEFAULT '',
            source_data_endpoint TEXT NOT NULL DEFAULT '',
            source_control_endpoint TEXT NOT NULL DEFAULT '',
            destination_data_endpoint TEXT NOT NULL DEFAULT '',
            destination_control_endpoint TEXT NOT NULL DEFAULT '',
            request_owner_control_endpoint TEXT NOT NULL DEFAULT '',
            connection_owner_control_endpoint TEXT NOT NULL DEFAULT '',
            resume_offset INTEGER NOT NULL,
            expected_size INTEGER NOT NULL,
            expected_sha256 TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            last_error TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (transfer_id)
                REFERENCES transfer_requests(transfer_id) ON DELETE CASCADE,
            UNIQUE (transfer_id, ordinal),
            CHECK (ordinal > 0),
            CHECK (mode IN (
                'local', 'direct_pull', 'direct_push',
                'source_push', 'destination_pull'
            )),
            CHECK (status IN (
                'planned', 'waiting_producer', 'waiting_consumer',
                'streaming', 'verifying', 'completed', 'failed',
                'expired', 'cancelled'
            )),
            CHECK (resume_offset >= 0),
            CHECK (expected_size >= 0)
        );

        CREATE INDEX IF NOT EXISTS transfer_attempts_active
            ON transfer_attempts(transfer_id, status, ordinal);
        """
    )
    _ensure_route_columns(connection)


def _ensure_route_columns(connection: sqlite3.Connection) -> None:
    existing = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(transfer_attempts)"
        ).fetchall()
    }
    for name in (
        "relay_data_endpoint",
        "source_data_endpoint",
        "source_control_endpoint",
        "destination_data_endpoint",
        "destination_control_endpoint",
        "request_owner_control_endpoint",
        "connection_owner_control_endpoint",
    ):
        if name not in existing:
            connection.execute(
                f"ALTER TABLE transfer_attempts ADD COLUMN {name} "
                "TEXT NOT NULL DEFAULT ''"
            )
