"""SQLite-backed settings for factor source storage roots."""

from __future__ import annotations

import sqlite3
import time

import settings as Settings
from tools.data.sqlite.db import connect_sqlite


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_source_roots (
            username TEXT PRIMARY KEY,
            source_root TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )


def ensure_factor_source_settings_sqlite_store() -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
    return str(Settings.CACHE_DB_PATH)


def load_factor_source_root(username: str) -> str | None:
    if not username:
        return None
    try:
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            _ensure_schema(conn)
            row = conn.execute(
                "SELECT source_root FROM factor_source_roots WHERE username = ?",
                (username,),
            ).fetchone()
            if row is None:
                return None
            source_root = str(row["source_root"] or "").strip()
            return source_root or None
    except Exception:
        return None


def save_factor_source_root(username: str, source_root: str | None) -> str:
    if not username:
        return str(Settings.CACHE_DB_PATH)
    normalized = str(source_root or "").strip()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        if normalized:
            conn.execute(
                """
                INSERT INTO factor_source_roots (username, source_root, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    source_root = excluded.source_root,
                    updated_at = excluded.updated_at
                """,
                (username, normalized, time.time()),
            )
        else:
            conn.execute("DELETE FROM factor_source_roots WHERE username = ?", (username,))
    return str(Settings.CACHE_DB_PATH)

