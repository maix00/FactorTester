"""One-way migration from the NAT transfer schema to WireGuard-direct v6."""

from __future__ import annotations

import json
import sqlite3
import time


LEGACY_REASON = "superseded by WireGuard-direct transfer topology"
_TERMINAL = {"completed", "failed", "expired", "cancelled"}
_OBSOLETE_TABLES = (
    "transfer_tickets",
    "transfer_attempts",
    "transfer_outbox",
    "transfer_inbox",
    "transfer_node_commands",
    "transfer_node_command_sequences",
    "transfer_node_presence",
    "transfer_requests",
)


def _exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if not _exists(connection, table):
        return set()
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def schema_version(connection: sqlite3.Connection) -> int:
    if not _exists(connection, "transfer_meta"):
        return 0
    row = connection.execute(
        "SELECT value FROM transfer_meta WHERE key='schema_version'"
    ).fetchone()
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("transfer database schema version is invalid") from exc


def needs_v6_migration(connection: sqlite3.Connection) -> bool:
    request_columns = _columns(connection, "transfer_requests")
    attempt_columns = _columns(connection, "transfer_attempts")
    return bool(
        "relay_owner_manager_id" in request_columns
        or "relay_owner_manager_id" in attempt_columns
        or "relay_data_endpoint" in attempt_columns
    )


def capture_legacy_rows(connection: sqlite3.Connection) -> tuple[list, list]:
    requests = (
        connection.execute("SELECT * FROM transfer_requests").fetchall()
        if _exists(connection, "transfer_requests")
        else []
    )
    attempts = (
        connection.execute("SELECT * FROM transfer_attempts").fetchall()
        if _exists(connection, "transfer_attempts")
        else []
    )
    return requests, attempts


def drop_obsolete_tables(connection: sqlite3.Connection) -> None:
    for table in _OBSOLETE_TABLES:
        connection.execute(f"DROP TABLE IF EXISTS {table}")


def restore_requests(connection: sqlite3.Connection, rows: list) -> None:
    for row in rows:
        status = str(row["status"])
        if status not in _TERMINAL:
            status = "failed"
        connection.execute(
            """
            INSERT INTO transfer_requests(
                transfer_id, idempotency_key, operation, status, principal,
                request_owner_manager_id, source_server_id,
                destination_server_id, storage_server_id, job_id,
                artifact_name, expected_size, expected_sha256, attempt,
                created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (
                row["transfer_id"], row["idempotency_key"], row["operation"],
                status, row["principal"], row["request_owner_manager_id"],
                row["source_server_id"], row["destination_server_id"],
                row["storage_server_id"], row["job_id"], row["artifact_name"],
                row["expected_size"], row["expected_sha256"],
                row["created_at"], row["updated_at"], row["expires_at"],
            ),
        )


def archive_attempts(
    connection: sqlite3.Connection,
    rows: list,
    *,
    now: float | None = None,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS transfer_legacy_attempts (
            attempt_id TEXT PRIMARY KEY,
            transfer_id TEXT NOT NULL,
            legacy_mode TEXT NOT NULL,
            legacy_status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            archived_at REAL NOT NULL,
            reason TEXT NOT NULL
        )
        """
    )
    archived_at = time.time() if now is None else float(now)
    for row in rows:
        payload = {key: row[key] for key in row.keys()}
        connection.execute(
            """
            INSERT OR IGNORE INTO transfer_legacy_attempts(
                attempt_id, transfer_id, legacy_mode, legacy_status,
                payload_json, archived_at, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["attempt_id"], row["transfer_id"], row["mode"],
                row["status"], json.dumps(payload, sort_keys=True),
                archived_at, LEGACY_REASON,
            ),
        )
