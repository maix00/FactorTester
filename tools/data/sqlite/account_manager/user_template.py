"""SQLite user-template access with one row per template."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite


TEMPLATE_TABLE = "account_templates"
LEGACY_COLLECTION_TABLE = "account_template_collections"


def _template_key(value: str | None) -> str:
    return str(value or "")


def _insert_templates(
    conn: sqlite3.Connection,
    username: str,
    kind: str,
    templates: list[dict[str, Any]],
    *,
    ff_alias: str = "",
    scope_key: str = "",
    updated_at: float | None = None,
) -> None:
    now = float(updated_at or time.time())
    rows = []
    for index, item in enumerate(templates):
        if not isinstance(item, dict):
            continue
        template_id = str(item.get("id") or f"__index__:{index}")
        rows.append(
            (
                username,
                kind,
                scope_key,
                ff_alias,
                template_id,
                index,
                str(item.get("name") or ""),
                str(item.get("ff_alias") or ""),
                json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                now,
            )
        )
    conn.executemany(
        f'''
        INSERT INTO "{TEMPLATE_TABLE}" (
            username, kind, scope_key, ff_alias, template_id, sort_order,
            name, item_ff_alias, payload_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        rows,
    )


def _migrate_legacy_collections(conn: sqlite3.Connection) -> None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (LEGACY_COLLECTION_TABLE,),
    ).fetchone()
    if exists is None:
        return

    rows = conn.execute(
        f'''
        SELECT username, kind, scope_key, ff_alias, payload_json, updated_at
        FROM "{LEGACY_COLLECTION_TABLE}"
        '''
    ).fetchall()
    for row in rows:
        try:
            data = json.loads(row["payload_json"])
        except Exception:
            data = []
        templates = data.get("templates", []) if isinstance(data, dict) else data
        if not isinstance(templates, list):
            templates = []
        conn.execute(
            f'''
            DELETE FROM "{TEMPLATE_TABLE}"
            WHERE username=? AND kind=? AND scope_key=? AND ff_alias=?
            ''',
            (row["username"], row["kind"], row["scope_key"], row["ff_alias"]),
        )
        _insert_templates(
            conn,
            row["username"],
            row["kind"],
            templates,
            scope_key=row["scope_key"],
            ff_alias=row["ff_alias"],
            updated_at=row["updated_at"],
        )
    conn.execute(f'DROP TABLE "{LEGACY_COLLECTION_TABLE}"')


def ensure_user_template_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f'''
        CREATE TABLE IF NOT EXISTS "{TEMPLATE_TABLE}" (
            username TEXT NOT NULL,
            kind TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            ff_alias TEXT NOT NULL,
            template_id TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            name TEXT NOT NULL,
            item_ff_alias TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (username, kind, scope_key, ff_alias, template_id)
        )
        '''
    )
    conn.execute(
        f'''
        CREATE INDEX IF NOT EXISTS idx_account_templates_collection_order
        ON "{TEMPLATE_TABLE}" (username, kind, scope_key, ff_alias, sort_order)
        '''
    )
    _migrate_legacy_collections(conn)


def load_user_templates(
    username: str,
    kind: str,
    ff_alias: str | None = None,
    scope_key: str | None = None,
) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_template_schema(conn)
        rows = conn.execute(
            f'''
            SELECT payload_json
            FROM "{TEMPLATE_TABLE}"
            WHERE username=? AND kind=? AND scope_key=? AND ff_alias=?
            ORDER BY sort_order
            ''',
            (username, kind, _template_key(scope_key), _template_key(ff_alias)),
        ).fetchall()
    result = []
    for row in rows:
        try:
            item = json.loads(row["payload_json"])
        except Exception:
            continue
        if isinstance(item, dict):
            result.append(item)
    return result


def list_user_template_metadata(
    username: str,
    kind: str,
    ff_alias: str | None = None,
    scope_key: str | None = None,
) -> list[dict[str, Any]]:
    """List lightweight template metadata without selecting snapshot payloads."""
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_template_schema(conn)
        rows = conn.execute(
            f'''
            SELECT template_id AS id, name, item_ff_alias AS ff_alias, updated_at
            FROM "{TEMPLATE_TABLE}"
            WHERE username=? AND kind=? AND scope_key=? AND ff_alias=?
            ORDER BY sort_order
            ''',
            (username, kind, _template_key(scope_key), _template_key(ff_alias)),
        ).fetchall()
    return [dict(row) for row in rows]


def load_user_template(
    username: str,
    kind: str,
    template_id: str,
    ff_alias: str | None = None,
    scope_key: str | None = None,
) -> dict[str, Any] | None:
    """Load one template payload by id."""
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_template_schema(conn)
        row = conn.execute(
            f'''
            SELECT payload_json
            FROM "{TEMPLATE_TABLE}"
            WHERE username=? AND kind=? AND scope_key=? AND ff_alias=? AND template_id=?
            ''',
            (
                username,
                kind,
                _template_key(scope_key),
                _template_key(ff_alias),
                str(template_id),
            ),
        ).fetchone()
    if row is None:
        return None
    try:
        item = json.loads(row["payload_json"])
    except Exception:
        return None
    return item if isinstance(item, dict) else None


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
    templates = payload.get("templates", []) if isinstance(payload, dict) else payload
    templates = [item for item in templates if isinstance(item, dict)]
    scope = _template_key(scope_key)
    family = _template_key(ff_alias)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_template_schema(conn)
        conn.execute(
            f'''
            DELETE FROM "{TEMPLATE_TABLE}"
            WHERE username=? AND kind=? AND scope_key=? AND ff_alias=?
            ''',
            (username, kind, scope, family),
        )
        _insert_templates(
            conn,
            username,
            kind,
            templates,
            scope_key=scope,
            ff_alias=family,
        )


def iter_user_template_collections() -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_template_schema(conn)
        rows = conn.execute(
            f'''
            SELECT username, kind, scope_key, ff_alias, MAX(updated_at) AS updated_at
            FROM "{TEMPLATE_TABLE}"
            GROUP BY username, kind, scope_key, ff_alias
            ORDER BY username, kind, scope_key, ff_alias
            '''
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["templates"] = load_user_templates(
            item["username"],
            item["kind"],
            ff_alias=item["ff_alias"],
            scope_key=item["scope_key"],
        )
        result.append(item)
    return result


def delete_user_template_collections(username: str) -> int:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_template_schema(conn)
        cursor = conn.execute(
            f'DELETE FROM "{TEMPLATE_TABLE}" WHERE username=?',
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
            f'''
            DELETE FROM "{TEMPLATE_TABLE}"
            WHERE username=? AND kind=? AND scope_key=? AND ff_alias=?
            ''',
            (username, kind, _template_key(scope_key), _template_key(ff_alias)),
        )
        return int(cursor.rowcount or 0)
