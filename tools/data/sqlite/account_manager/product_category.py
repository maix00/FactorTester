"""SQLite storage for account-owned product category definitions."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite


def ensure_product_category_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_product_categories (
            username TEXT NOT NULL,
            category_id TEXT NOT NULL,
            sort_index INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (username, category_id)
        )
        """
    )

def load_product_categories(username: str) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_product_category_schema(conn)
        rows = conn.execute(
            """
            SELECT payload_json
            FROM account_product_categories
            WHERE username = ?
            ORDER BY sort_index, category_id
            """,
            (username,),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            value = json.loads(row["payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            result.append(value)
    from tools.data.sqlite.account_manager.domain_sync import overlay_entities
    return overlay_entities(username, 'product_category', result, id_key='id')


def save_product_categories(
    username: str,
    categories: list[dict[str, Any]],
) -> None:
    now = time.time()
    normalized = [dict(item) for item in categories if isinstance(item, dict)]
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_product_category_schema(conn)
        conn.execute(
            "DELETE FROM account_product_categories WHERE username = ?",
            (username,),
        )
        for sort_index, category in enumerate(normalized):
            category_id = str(category.get("id") or "").strip()
            if not category_id:
                continue
            conn.execute(
                """
                INSERT INTO account_product_categories (
                    username, category_id, sort_index, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    username,
                    category_id,
                    sort_index,
                    json.dumps(category, ensure_ascii=False, separators=(",", ":")),
                    now,
                ),
            )
