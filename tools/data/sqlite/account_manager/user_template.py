"""SQLite user-template collection access."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

import Settings
from tools.data.sqlite.db import connect_sqlite


def ensure_user_template_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_template_collections (
            username TEXT NOT NULL,
            kind TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            ff_alias TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (username, kind, scope_key, ff_alias)
        )
        """
    )


def _template_key(value: str | None) -> str:
    return str(value or "")


def load_user_templates(
    username: str,
    kind: str,
    ff_alias: str | None = None,
    scope_key: str | None = None,
) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_template_schema(conn)
        row = conn.execute(
            """
            SELECT payload_json
            FROM account_template_collections
            WHERE username = ? AND kind = ? AND scope_key = ? AND ff_alias = ?
            """,
            (username, kind, _template_key(scope_key), _template_key(ff_alias)),
        ).fetchone()
    if row is None:
        return []
    try:
        data = json.loads(row["payload_json"])
    except Exception:
        return []
    if isinstance(data, dict) and isinstance(data.get("templates"), list):
        return [item for item in data["templates"] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def save_user_templates(
    username: str,
    kind: str,
    templates: list[dict[str, Any]],
    ff_alias: str | None = None,
    scope_key: str | None = None,
) -> None:
    save_user_template_payload(
        username,
        kind,
        [item for item in templates if isinstance(item, dict)],
        ff_alias=ff_alias,
        scope_key=scope_key,
    )


def save_user_template_payload(
    username: str,
    kind: str,
    payload: dict[str, Any] | list[dict[str, Any]],
    ff_alias: str | None = None,
    scope_key: str | None = None,
) -> None:
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_template_schema(conn)
        conn.execute(
            """
            INSERT INTO account_template_collections (
                username, kind, scope_key, ff_alias, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(username, kind, scope_key, ff_alias)
            DO UPDATE SET payload_json = excluded.payload_json, updated_at = excluded.updated_at
            """,
            (username, kind, _template_key(scope_key), _template_key(ff_alias), payload_json, now),
        )


def iter_user_template_collections() -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_template_schema(conn)
        rows = conn.execute(
            """
            SELECT username, kind, scope_key, ff_alias, payload_json, updated_at
            FROM account_template_collections
            ORDER BY username, kind, scope_key, ff_alias
            """
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            payload = json.loads(item.pop("payload_json"))
        except Exception:
            payload = {"templates": []}
        item["templates"] = payload.get("templates", []) if isinstance(payload, dict) else []
        result.append(item)
    return result


def delete_user_template_collections(username: str) -> int:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_template_schema(conn)
        cursor = conn.execute(
            "DELETE FROM account_template_collections WHERE username = ?",
            (username,),
        )
        return int(cursor.rowcount or 0)


def delete_user_template_collection(
    username: str,
    kind: str,
    ff_alias: str | None = None,
    scope_key: str | None = None,
) -> int:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_template_schema(conn)
        cursor = conn.execute(
            """
            DELETE FROM account_template_collections
            WHERE username = ? AND kind = ? AND scope_key = ? AND ff_alias = ?
            """,
            (username, kind, _template_key(scope_key), _template_key(ff_alias)),
        )
        return int(cursor.rowcount or 0)
