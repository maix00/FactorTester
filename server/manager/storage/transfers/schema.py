"""Versioned composition of the Manager-local transfer schema."""

from __future__ import annotations

import sqlite3

from server.manager.storage.transfers.migrations import (
    archive_attempts,
    capture_legacy_rows,
    drop_obsolete_tables,
    needs_v6_migration,
    restore_requests,
    schema_version,
)
from server.manager.storage.transfers.schema_attempts import ensure_attempt_schema
from server.manager.storage.transfers.schema_endpoints import ensure_endpoint_schema
from server.manager.storage.transfers.schema_nodes import ensure_node_schema
from server.manager.storage.transfers.schema_requests import ensure_request_schema
from server.manager.storage.transfers.schema_tickets import ensure_ticket_schema


TRANSFER_SCHEMA_VERSION = 8


def _ensure_current_tables(connection: sqlite3.Connection) -> None:
    ensure_request_schema(connection)
    ensure_attempt_schema(connection)
    ensure_ticket_schema(connection)
    ensure_node_schema(connection)
    ensure_endpoint_schema(connection)


def ensure_transfer_schema(connection: sqlite3.Connection) -> None:
    version = schema_version(connection)
    if version > TRANSFER_SCHEMA_VERSION:
        raise RuntimeError(
            f"unsupported transfer schema version {version}; "
            f"maximum is {TRANSFER_SCHEMA_VERSION}"
        )
    if needs_v6_migration(connection):
        requests, attempts = capture_legacy_rows(connection)
        connection.execute("PRAGMA foreign_keys = OFF")
        drop_obsolete_tables(connection)
        _ensure_current_tables(connection)
        restore_requests(connection, requests)
        archive_attempts(connection, attempts)
        connection.execute("PRAGMA foreign_keys = ON")
    else:
        _ensure_current_tables(connection)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS transfer_meta "
        "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        """
        INSERT INTO transfer_meta(key, value) VALUES ('schema_version', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (str(TRANSFER_SCHEMA_VERSION),),
    )
