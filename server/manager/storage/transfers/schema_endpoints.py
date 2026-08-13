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

        CREATE TABLE IF NOT EXISTS transfer_node_advertisement_nonces (
            node_id TEXT NOT NULL,
            nonce TEXT NOT NULL,
            expires_at REAL NOT NULL,
            PRIMARY KEY (node_id, nonce),
            FOREIGN KEY (node_id) REFERENCES transfer_node_identities(node_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS transfer_node_advertisement_nonce_expiry
            ON transfer_node_advertisement_nonces(expires_at);

        CREATE TABLE IF NOT EXISTS transfer_node_advertisement_state (
            node_id TEXT PRIMARY KEY,
            latest_issued_at REAL NOT NULL,
            latest_nonce TEXT NOT NULL,
            expires_at REAL NOT NULL,
            FOREIGN KEY (node_id) REFERENCES transfer_node_identities(node_id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS transfer_node_advertisement_clock (
            node_id TEXT PRIMARY KEY,
            last_issued_at REAL NOT NULL,
            FOREIGN KEY (node_id) REFERENCES transfer_node_identities(node_id)
                ON DELETE CASCADE
        );
        """
    )
