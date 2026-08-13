"""Hash-only transfer capability records shared with the local 7997 service."""

from __future__ import annotations

import sqlite3


def ensure_ticket_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS transfer_tickets (
            ticket_id TEXT PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            transfer_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            role TEXT NOT NULL,
            principal TEXT NOT NULL,
            node_id TEXT NOT NULL DEFAULT '',
            start_offset INTEGER NOT NULL,
            end_offset INTEGER NOT NULL,
            use_count INTEGER NOT NULL DEFAULT 0,
            max_uses INTEGER NOT NULL DEFAULT 0,
            issued_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            revoked_at REAL,
            last_used_at REAL,
            CHECK (role IN (
                'client_upload', 'producer', 'consumer', 'origin_read',
                'destination_write'
            )),
            CHECK (start_offset >= 0),
            CHECK (end_offset >= start_offset),
            CHECK (use_count >= 0),
            CHECK (max_uses >= 0)
        );

        CREATE INDEX IF NOT EXISTS transfer_tickets_expiry
            ON transfer_tickets(expires_at, revoked_at);
        """
    )
