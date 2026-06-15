"""SQLite store for source access visits."""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import date
from typing import Any

from tools.data.data_source.DataHub import DataHub

logger = logging.getLogger(__name__)

TABLE_NAME = "source_visits"


def _connect() -> sqlite3.Connection:
    return DataHub.get_instance().connect_store("openctp")


def ensure_visits_store() -> str:
    hub = DataHub.get_instance()
    with hub.connect_store("openctp") as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS source_visits (
                source_key TEXT PRIMARY KEY,
                source_label TEXT NOT NULL,
                last_access_date TEXT NOT NULL,
                last_access_at REAL NOT NULL
            )
            """
        )
    return hub._get_sqlite_store("openctp").path()


def record_visit(source_key: str, *, source_label: str, access_date: date | str | None = None) -> str:
    visit_date = access_date.isoformat() if isinstance(access_date, date) else str(access_date or date.today().isoformat())
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO source_visits (source_key, source_label, last_access_date, last_access_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                source_label = excluded.source_label,
                last_access_date = excluded.last_access_date,
                last_access_at = excluded.last_access_at
            """,
            (source_key, source_label, visit_date, time.time()),
        )
    return visit_date


def get_visit(source_key: str) -> dict[str, Any] | None:
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT source_key, source_label, last_access_date, last_access_at
                FROM source_visits
                WHERE source_key = ?
                """,
                (source_key,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)
    except Exception:
        return None


def get_latest_access_date(source_key: str) -> str | None:
    visit = get_visit(source_key)
    if visit is None:
        return None
    return str(visit["last_access_date"])
