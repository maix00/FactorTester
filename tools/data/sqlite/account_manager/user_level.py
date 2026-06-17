"""SQLite organization and user-level table access."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

import Settings
from tools.data.sqlite.db import connect_sqlite


def ensure_user_level_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS organizations (
            id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS levels (
            id TEXT PRIMARY KEY,
            organization_id TEXT,
            name TEXT,
            parent_level_id TEXT,
            manager_username TEXT,
            updated_at REAL NOT NULL
        )
        """
    )


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def load_organizations() -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_level_schema(conn)
        rows = conn.execute(
            """
            SELECT id, name, description, updated_at
            FROM organizations
            ORDER BY id
            """
        ).fetchall()
    return _rows_to_dicts(rows)


def save_organizations(organizations: list[dict[str, Any]]) -> None:
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_level_schema(conn)
        conn.execute("DELETE FROM organizations")
        conn.executemany(
            """
            INSERT INTO organizations (id, name, description, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    row.get("id"),
                    row.get("name"),
                    row.get("description"),
                    now,
                )
                for row in organizations
                if isinstance(row, dict)
            ],
        )


def load_levels() -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_level_schema(conn)
        rows = conn.execute(
            """
            SELECT id, organization_id, name, parent_level_id, manager_username, updated_at
            FROM levels
            ORDER BY organization_id, id
            """
        ).fetchall()
    return _rows_to_dicts(rows)


def save_levels(levels: list[dict[str, Any]]) -> None:
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_level_schema(conn)
        conn.execute("DELETE FROM levels")
        conn.executemany(
            """
            INSERT INTO levels (id, organization_id, name, parent_level_id, manager_username, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.get("id"),
                    row.get("organization_id"),
                    row.get("name"),
                    row.get("parent_level_id"),
                    row.get("manager_username"),
                    now,
                )
                for row in levels
                if isinstance(row, dict)
            ],
        )
