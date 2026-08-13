"""Latest advertised public and WireGuard endpoints for each node."""

from __future__ import annotations

import sqlite3


def ensure_endpoint_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS transfer_node_endpoints (
            node_id TEXT PRIMARY KEY,
            client_control_endpoint TEXT NOT NULL,
            client_data_endpoint TEXT NOT NULL,
            peer_control_endpoint TEXT NOT NULL,
            peer_data_endpoint TEXT NOT NULL,
            observed_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            online INTEGER NOT NULL,
            CHECK (online IN (0, 1))
        );

        CREATE INDEX IF NOT EXISTS transfer_node_endpoints_expiry
            ON transfer_node_endpoints(online, expires_at);
        """
    )
