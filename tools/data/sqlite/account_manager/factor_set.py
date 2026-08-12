"""SQLite storage for server-registered user factor sets."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite


def ensure_factor_set_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_factor_sets (
            username TEXT NOT NULL,
            target_ref TEXT NOT NULL,
            set_ref TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (username, target_ref)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_account_factor_sets_stable_ref
        ON account_factor_sets (username, set_ref, updated_at DESC)
        """
    )


def list_factor_sets(username: str) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_set_schema(conn)
        rows = conn.execute(
            """
            SELECT payload_json
            FROM account_factor_sets
            WHERE username = ?
            ORDER BY updated_at DESC, target_ref
            """,
            (username,),
        ).fetchall()
    return [
        value for row in rows
        if isinstance((value := _payload(row["payload_json"])), dict)
    ]


def get_factor_set(username: str, target_ref: str) -> dict[str, Any] | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_set_schema(conn)
        row = conn.execute(
            """
            SELECT payload_json
            FROM account_factor_sets
            WHERE username = ? AND target_ref = ?
            """,
            (username, target_ref),
        ).fetchone()
    return _payload(row["payload_json"]) if row is not None else None


def save_factor_set(username: str, value: dict[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    now = time.time()
    payload["updated_at"] = now
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_set_schema(conn)
        conn.execute(
            """
            INSERT INTO account_factor_sets (
                username, target_ref, set_ref, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(username, target_ref) DO UPDATE SET
                set_ref = excluded.set_ref,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (
                username,
                payload["target_ref"],
                payload["set_ref"],
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                now,
            ),
        )
    return payload


def delete_factor_set(username: str, target_ref: str) -> bool:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_set_schema(conn)
        cursor = conn.execute(
            "DELETE FROM account_factor_sets WHERE username = ? AND target_ref = ?",
            (username, target_ref),
        )
    return cursor.rowcount > 0


def _payload(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None
