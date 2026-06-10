"""SQLite mirror for user-related JSON data.

This keeps sqlite-web pointed at actual SQLite files while the canonical
storage remains the existing JSON files under ``DATA_DIR/users``.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from scripts.data_dir import DATA_DIR
from server.services.local_sql_data import SQLiteStore, register_store


USER_SQLITE_DIR = Path(DATA_DIR) / "cache" / "sqlite-web"
USER_SQLITE_PATH = USER_SQLITE_DIR / "users.sqlite"


def _connect() -> sqlite3.Connection:
    USER_SQLITE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(USER_SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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
    try:
        from server.services.accounts import (
            ACCOUNTS_FILE,
            ORGANIZATIONS_FILE,
            LEVELS_FILE,
        )
    except Exception:
        return str(USER_SQLITE_PATH)

    accounts = _read_json(ACCOUNTS_FILE)
    organizations = _read_json(ORGANIZATIONS_FILE)
    levels = _read_json(LEVELS_FILE)

    with _connect() as conn:
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
    return str(USER_SQLITE_PATH)


def ensure_user_sqlite_store() -> str:
    """Ensure the SQLite mirror exists and is up-to-date."""
    return sync_user_sqlite_store()


register_store(
    SQLiteStore(
        key="users",
        label="用户数据镜像",
        path_getter=lambda: str(USER_SQLITE_PATH),
        ensure=ensure_user_sqlite_store,
    )
)
