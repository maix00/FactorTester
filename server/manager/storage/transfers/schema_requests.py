"""Durable request-owner transfer table."""

from __future__ import annotations

import sqlite3


def ensure_request_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS transfer_requests (
            transfer_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            operation TEXT NOT NULL,
            status TEXT NOT NULL,
            principal TEXT NOT NULL,
            request_owner_manager_id TEXT NOT NULL,
            source_server_id TEXT NOT NULL,
            destination_server_id TEXT NOT NULL,
            storage_server_id TEXT NOT NULL,
            job_id TEXT NOT NULL DEFAULT '',
            artifact_name TEXT NOT NULL DEFAULT '',
            expected_size INTEGER NOT NULL,
            expected_sha256 TEXT NOT NULL DEFAULT '',
            attempt INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            CHECK (operation IN ('download', 'upload')),
            CHECK (status IN (
                'created', 'planned', 'dispatched', 'streaming',
                'verifying', 'retry_wait', 'completed', 'failed',
                'expired', 'cancelled'
            )),
            CHECK (expected_size >= 0),
            CHECK (attempt >= 0)
        );

        CREATE INDEX IF NOT EXISTS transfer_requests_status_expiry
            ON transfer_requests(status, expires_at, created_at);
        CREATE INDEX IF NOT EXISTS transfer_requests_source_status
            ON transfer_requests(source_server_id, status, created_at);
        """
    )
