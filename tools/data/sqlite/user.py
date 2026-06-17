"""SQLite mirror for user-related JSON data.

This keeps sqlite-web pointed at actual SQLite files while the canonical
storage remains the existing JSON files under ``DATA_DIR/users``.
"""
from __future__ import annotations

import json
import time
from typing import Any

import Settings
from tools.data.accounts_store import ACCOUNTS_FILE, ORGANIZATIONS_FILE, LEVELS_FILE
from tools.data.sqlite.db import connect_sqlite

USER_SQLITE_PATH = Settings.CACHE_DB_PATH
def _read_json(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            username TEXT PRIMARY KEY,
            alias TEXT,
            salt TEXT,
            hash TEXT,
            role TEXT,
            is_admin INTEGER,
            organization_id TEXT,
            organization_name TEXT,
            level_id TEXT,
            parent_username TEXT,
            updated_at REAL NOT NULL
        )
        """
    )
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


def _replace_rows(conn: sqlite3.Connection, table: str, rows: list[dict[str, Any]], columns: list[str], key: str) -> None:
    conn.execute(f"DELETE FROM {table}")
    placeholders = ", ".join("?" for _ in columns)
    insert_sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    now = time.time()
    payload = []
    for row in rows:
        payload.append(tuple(
            1 if column == "is_admin" and row.get(column) else
            row.get(column)
            for column in columns
        ) + (now,))
    if not payload:
        return
    conn.executemany(insert_sql, payload)


def sync_user_sqlite_store() -> str:
    """Sync JSON user data into the SQLite mirror."""
    accounts = _read_json(ACCOUNTS_FILE)
    organizations = _read_json(ORGANIZATIONS_FILE)
    levels = _read_json(LEVELS_FILE)

    with connect_sqlite(Settings.CACHE_DB_PATH, foreign_keys=True) as conn:
        _ensure_schema(conn)
        now = time.time()
        conn.execute("DELETE FROM accounts")
        conn.execute("DELETE FROM organizations")
        conn.execute("DELETE FROM levels")
        conn.executemany(
            """
            INSERT INTO accounts (
                username, alias, salt, hash, role, is_admin,
                organization_id, organization_name, level_id, parent_username, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.get("username"),
                    row.get("alias"),
                    row.get("salt"),
                    row.get("hash"),
                    row.get("role"),
                    1 if row.get("is_admin") else 0,
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
    return str(Settings.CACHE_DB_PATH)


def ensure_user_sqlite_store() -> str:
    """Ensure the SQLite mirror exists and is up-to-date."""
    return sync_user_sqlite_store()
