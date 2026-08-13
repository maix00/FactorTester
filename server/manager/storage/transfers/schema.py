"""Versioned composition of the Manager-local transfer schema."""

from __future__ import annotations

import sqlite3

from server.manager.storage.transfers.schema_attempts import ensure_attempt_schema
from server.manager.storage.transfers.schema_commands import ensure_command_schema
from server.manager.storage.transfers.schema_nodes import ensure_node_schema
from server.manager.storage.transfers.schema_node_control import (
    ensure_node_control_schema,
)
from server.manager.storage.transfers.schema_requests import ensure_request_schema
from server.manager.storage.transfers.schema_tickets import ensure_ticket_schema


TRANSFER_SCHEMA_VERSION = 5


def ensure_transfer_schema(connection: sqlite3.Connection) -> None:
    ensure_request_schema(connection)
    ensure_attempt_schema(connection)
    ensure_command_schema(connection)
    ensure_ticket_schema(connection)
    ensure_node_schema(connection)
    ensure_node_control_schema(connection)
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
