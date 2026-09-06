"""SQLite storage for user product groups."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite


def ensure_product_group_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_product_groups (
            username TEXT NOT NULL,
            group_name TEXT NOT NULL,
            sort_index INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (username, group_name)
        )
        """
    )


def load_product_groups(username: str) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_product_group_schema(conn)
        rows = conn.execute(
            """
            SELECT payload_json
            FROM account_product_groups
            WHERE username = ?
            ORDER BY sort_index, group_name
            """,
            (username,),
        ).fetchall()
    groups: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except Exception:
            continue
        if isinstance(payload, dict):
            groups.append(payload)
    from tools.data.sqlite.account_manager.domain_sync import overlay_entities
    return overlay_entities(username, 'product_group', groups, id_key='id')


def save_product_groups(username: str, groups: list[dict[str, Any]]) -> None:
    now = time.time()
    normalized = [dict(group) for group in groups if isinstance(group, dict)]
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_product_group_schema(conn)
        conn.execute("DELETE FROM account_product_groups WHERE username = ?", (username,))
        for sort_index, group in enumerate(normalized):
            name = str(group.get("name") or "").strip()
            if not name:
                continue
            group["name"] = name
            conn.execute(
                """
                INSERT INTO account_product_groups (
                    username, group_name, sort_index, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    username,
                    name,
                    sort_index,
                    json.dumps(group, ensure_ascii=False, separators=(",", ":")),
                    now,
                ),
            )
