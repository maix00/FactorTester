"""Public-Manager command queue and authenticated node presence cache."""

from __future__ import annotations

import sqlite3


def ensure_node_control_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS transfer_node_command_sequences (
            target_server_id TEXT PRIMARY KEY,
            last_sequence INTEGER NOT NULL,
            CHECK (last_sequence >= 0)
        );

        CREATE TABLE IF NOT EXISTS transfer_node_commands (
            command_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            transfer_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            command_type TEXT NOT NULL,
            target_server_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            acknowledged_at REAL,
            UNIQUE (target_server_id, sequence),
            CHECK (sequence > 0)
        );

        CREATE INDEX IF NOT EXISTS transfer_node_commands_pending
            ON transfer_node_commands(
                target_server_id, acknowledged_at, expires_at, sequence
            );

        CREATE TABLE IF NOT EXISTS transfer_node_presence (
            node_id TEXT PRIMARY KEY,
            connection_owner_manager_id TEXT NOT NULL,
            connection_id TEXT NOT NULL,
            data_endpoint TEXT NOT NULL,
            reachable_from_json TEXT NOT NULL,
            observed_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            online INTEGER NOT NULL,
            CHECK (online IN (0, 1))
        );

        CREATE INDEX IF NOT EXISTS transfer_node_presence_expiry
            ON transfer_node_presence(online, expires_at);
        """
    )
