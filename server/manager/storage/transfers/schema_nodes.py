"""Public node identities and one-time authentication challenges."""

from __future__ import annotations

import sqlite3


def ensure_node_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS transfer_node_identities (
            node_id TEXT PRIMARY KEY,
            algorithm TEXT NOT NULL,
            public_key TEXT NOT NULL,
            fingerprint TEXT NOT NULL UNIQUE,
            enrolled_at REAL NOT NULL,
            rotated_at REAL,
            revoked_at REAL,
            CHECK (algorithm = 'Ed25519')
        );

        CREATE TABLE IF NOT EXISTS transfer_node_challenges (
            challenge_id TEXT PRIMARY KEY,
            challenge_hash TEXT NOT NULL UNIQUE,
            node_id TEXT NOT NULL,
            issued_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            used_at REAL,
            FOREIGN KEY (node_id)
                REFERENCES transfer_node_identities(node_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS transfer_node_challenges_expiry
            ON transfer_node_challenges(node_id, expires_at, used_at);
        """
    )
