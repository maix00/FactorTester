"""SQLite schema for bounded 7997/17997 transfer telemetry."""

from __future__ import annotations

import sqlite3


def ensure_telemetry_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS transfer_telemetry (
            attempt_id TEXT PRIMARY KEY,
            transfer_id TEXT NOT NULL,
            server_id TEXT NOT NULL,
            object_kind TEXT NOT NULL,
            operation TEXT NOT NULL,
            mode TEXT NOT NULL,
            surface TEXT NOT NULL,
            action TEXT NOT NULL,
            source_server_id TEXT NOT NULL,
            destination_server_id TEXT NOT NULL,
            expected_bytes INTEGER NOT NULL,
            transferred_bytes INTEGER NOT NULL DEFAULT 0,
            started_at REAL NOT NULL,
            finished_at REAL NOT NULL,
            duration_ms INTEGER NOT NULL,
            status TEXT NOT NULL,
            failure_reason TEXT NOT NULL DEFAULT '',
            CHECK (expected_bytes >= 0),
            CHECK (transferred_bytes >= 0),
            CHECK (duration_ms >= 0)
        );

        CREATE INDEX IF NOT EXISTS transfer_telemetry_started
            ON transfer_telemetry(started_at);
        CREATE INDEX IF NOT EXISTS transfer_telemetry_kind_operation
            ON transfer_telemetry(object_kind, operation, started_at);
        CREATE INDEX IF NOT EXISTS transfer_telemetry_status
            ON transfer_telemetry(status, started_at);

        CREATE TABLE IF NOT EXISTS transfer_active_streams (
            stream_id TEXT PRIMARY KEY,
            attempt_id TEXT NOT NULL,
            transfer_id TEXT NOT NULL,
            server_id TEXT NOT NULL,
            object_kind TEXT NOT NULL,
            operation TEXT NOT NULL,
            mode TEXT NOT NULL,
            surface TEXT NOT NULL,
            action TEXT NOT NULL,
            expected_bytes INTEGER NOT NULL,
            transferred_bytes INTEGER NOT NULL DEFAULT 0,
            started_at REAL NOT NULL,
            last_seen_at REAL NOT NULL,
            process_instance_id TEXT NOT NULL,
            CHECK (expected_bytes >= 0),
            CHECK (transferred_bytes >= 0)
        );

        CREATE INDEX IF NOT EXISTS transfer_active_streams_seen
            ON transfer_active_streams(last_seen_at);
        CREATE INDEX IF NOT EXISTS transfer_active_streams_dimensions
            ON transfer_active_streams(surface, operation, object_kind);
        """
    )


__all__ = ["ensure_telemetry_schema"]
