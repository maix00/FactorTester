"""SQLite store for factor source code."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

import Settings
from tools.data.sqlite.db import connect_sqlite

SOURCE_TABLE = "factor_family_sources"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SOURCE_TABLE} (
            source_kind TEXT NOT NULL,
            owner_username TEXT NOT NULL DEFAULT '',
            factor_id TEXT NOT NULL,
            factor_name TEXT NOT NULL DEFAULT '',
            source_code TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL,
            PRIMARY KEY (source_kind, owner_username, factor_id)
        )
        """
    )


def ensure_factor_source_sqlite_store() -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
    return str(Settings.CACHE_DB_PATH)


def _load_source(source_kind: str, owner_username: str, factor_id: str) -> str | None:
    try:
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            _ensure_schema(conn)
            row = conn.execute(
                """
                SELECT source_code
                FROM factor_family_sources
                WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
                """,
                (source_kind, owner_username or "", factor_id),
            ).fetchone()
            if row is None:
                return None
            source_code = str(row["source_code"] or "")
            return source_code or None
    except Exception:
        return None


def get_factor_source_record(source_kind: str, owner_username: str, factor_id: str) -> dict[str, Any] | None:
    try:
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            _ensure_schema(conn)
            row = conn.execute(
                """
                SELECT source_kind, owner_username, factor_id, factor_name, source_code, updated_at
                FROM factor_family_sources
                WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
                """,
                (source_kind, owner_username or "", factor_id),
            ).fetchone()
            if row is None:
                return None
            return {
                "source_kind": row["source_kind"],
                "owner_username": row["owner_username"],
                "factor_id": row["factor_id"],
                "factor_name": row["factor_name"],
                "source_code": row["source_code"],
                "updated_at": float(row["updated_at"] or 0.0),
            }
    except Exception:
        return None


def load_factor_source(source_kind: str, owner_username: str, factor_id: str) -> str | None:
    return _load_source(source_kind, owner_username, factor_id)


def upsert_factor_source(
    source_kind: str,
    owner_username: str,
    factor_id: str,
    factor_name: str,
    source_code: str,
) -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO factor_family_sources (
                source_kind, owner_username, factor_id, factor_name, source_code, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_kind, owner_username, factor_id) DO UPDATE SET
                factor_name = excluded.factor_name,
                source_code = excluded.source_code,
                updated_at = excluded.updated_at
            """,
            (
                source_kind,
                owner_username or "",
                factor_id,
                factor_name or factor_id,
                source_code or "",
                time.time(),
            ),
        )
    return str(Settings.CACHE_DB_PATH)


def delete_factor_source(source_kind: str, owner_username: str, factor_id: str) -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            DELETE FROM factor_family_sources
            WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
            """,
            (source_kind, owner_username or "", factor_id),
        )
    return str(Settings.CACHE_DB_PATH)


def rename_factor_source(
    source_kind: str,
    owner_username: str,
    old_factor_id: str,
    new_factor_id: str,
    new_factor_name: str,
) -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT source_code, factor_name, updated_at
            FROM factor_family_sources
            WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
            """,
            (source_kind, owner_username or "", old_factor_id),
        ).fetchone()
        if row is None:
            return str(Settings.CACHE_DB_PATH)
        conn.execute(
            """
            DELETE FROM factor_family_sources
            WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
            """,
            (source_kind, owner_username or "", old_factor_id),
        )
        conn.execute(
            """
            INSERT INTO factor_family_sources (
                source_kind, owner_username, factor_id, factor_name, source_code, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_kind, owner_username, factor_id) DO UPDATE SET
                factor_name = excluded.factor_name,
                source_code = excluded.source_code,
                updated_at = excluded.updated_at
            """,
            (
                source_kind,
                owner_username or "",
                new_factor_id,
                new_factor_name or new_factor_id,
                row["source_code"],
                time.time(),
            ),
        )
    return str(Settings.CACHE_DB_PATH)


def list_factor_sources(source_kind: str) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT source_kind, owner_username, factor_id, factor_name, source_code, updated_at
            FROM factor_family_sources
            WHERE source_kind = ?
            ORDER BY owner_username, factor_id
            """,
            (source_kind,),
        ).fetchall()
    return [
        {
            "source_kind": row["source_kind"],
            "owner_username": row["owner_username"],
            "factor_id": row["factor_id"],
            "factor_name": row["factor_name"],
            "source_code": row["source_code"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]

