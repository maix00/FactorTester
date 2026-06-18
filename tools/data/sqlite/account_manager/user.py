"""SQLite account table access."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

import Settings
from tools.data.sqlite.db import connect_sqlite


def ensure_user_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            username TEXT PRIMARY KEY,
            alias TEXT,
            salt TEXT,
            hash TEXT,
            role TEXT,
            is_admin INTEGER,
            is_developer INTEGER,
            organization_id TEXT,
            organization_name TEXT,
            level_id TEXT,
            parent_username TEXT,
            updated_at REAL NOT NULL
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()}
    if "is_developer" not in columns:
        conn.execute("ALTER TABLE accounts ADD COLUMN is_developer INTEGER DEFAULT 0")


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def load_accounts() -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_schema(conn)
        rows = conn.execute(
            """
            SELECT username, alias, salt, hash, role, is_admin, is_developer,
                   organization_id, organization_name, level_id, parent_username, updated_at
            FROM accounts
            ORDER BY username
            """
        ).fetchall()
    return _rows_to_dicts(rows)


def save_accounts(accounts: list[dict[str, Any]]) -> None:
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_schema(conn)
        conn.execute("DELETE FROM accounts")
        conn.executemany(
            """
            INSERT INTO accounts (
                username, alias, salt, hash, role, is_admin, is_developer,
                organization_id, organization_name, level_id, parent_username, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.get("username"),
                    row.get("alias"),
                    row.get("salt"),
                    row.get("hash"),
                    row.get("role"),
                    1 if row.get("is_admin") else 0,
                    1 if row.get("is_developer") else 0,
                    row.get("organization_id"),
                    row.get("organization_name"),
                    row.get("level_id"),
                    row.get("parent_username"),
                    now,
                )
                for row in accounts
                if isinstance(row, dict)
            ],
        )
