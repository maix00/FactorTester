"""SQLite persistence and API projection for Graph display translations."""

from __future__ import annotations

from copy import deepcopy
import sqlite3
import time
from typing import Any, Mapping

import orjson

import settings as Settings
from server.services.research_graph.presentation_contract import (
    normalize_graph_locale,
    validate_presentation,
)
from server.services.research_graph.protocol import validate_graph
from tools.data.sqlite.db import connect_sqlite


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the current table and collapse the old revision history once."""
    existing = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='research_graph_presentations'
        """
    ).fetchone()
    if existing is not None:
        columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(research_graph_presentations)"
            ).fetchall()
        }
        if "translation_revision" in columns or "translation_hash" in columns:
            _migrate_revision_table(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_graph_presentations (
            graph_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            locale TEXT NOT NULL,
            presentation_json TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (graph_id, version, locale)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_graph_presentations_locale
        ON research_graph_presentations(graph_id, version, locale)
        """
    )


def register_presentation(
    graph: Mapping[str, Any],
    presentation: Mapping[str, Any],
    *,
    actor: str,
) -> dict[str, Any]:
    """Replace the current display overlay for one Graph version and locale."""
    canonical = _canonical_graph(graph)
    normalized = validate_presentation(canonical, presentation)
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO research_graph_presentations (
                graph_id, version, locale, presentation_json, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(graph_id, version, locale) DO UPDATE SET
                presentation_json=excluded.presentation_json,
                created_by=excluded.created_by,
                created_at=excluded.created_at
            """,
            (
                canonical["graph_id"],
                int(canonical["version"]),
                normalized["locale"],
                orjson.dumps(normalized, option=orjson.OPT_SORT_KEYS).decode(),
                str(actor),
                now,
            ),
        )
        row = conn.execute(
            """
            SELECT * FROM research_graph_presentations
            WHERE graph_id=? AND version=? AND locale=?
            """,
            (
                canonical["graph_id"],
                int(canonical["version"]),
                normalized["locale"],
            ),
        ).fetchone()
    return _row_payload(row)


def load_presentation(
    *,
    graph_id: str,
    version: int,
    locale: str,
) -> dict[str, Any] | None:
    normalized_locale = normalize_graph_locale(locale)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT * FROM research_graph_presentations
            WHERE graph_id=? AND version=? AND locale=?
            """,
            (graph_id, int(version), normalized_locale),
        ).fetchone()
    return _row_payload(row) if row is not None else None


def list_presentations(*, graph_id: str, version: int) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT * FROM research_graph_presentations
            WHERE graph_id=? AND version=? ORDER BY locale
            """,
            (graph_id, int(version)),
        ).fetchall()
    return [_row_payload(row) for row in rows]


def attach_presentation(
    graph: Mapping[str, Any],
    *,
    locale: str | None,
) -> dict[str, Any]:
    """Attach display text without altering canonical Graph identity."""
    value = deepcopy(dict(graph))
    if locale is None:
        return value
    normalized_locale = normalize_graph_locale(locale)
    presentation = load_presentation(
        graph_id=str(value["graph_id"]),
        version=int(value["version"]),
        locale=normalized_locale,
    )
    value["presentation_locale"] = normalized_locale
    value["presentation_status"] = "available" if presentation else "missing"
    value["presentation"] = presentation
    return value


def _migrate_revision_table(conn: sqlite3.Connection) -> None:
    """Keep only the newest locale row from the previous display history."""
    legacy = "research_graph_presentations_legacy"
    conn.execute(f'ALTER TABLE research_graph_presentations RENAME TO "{legacy}"')
    conn.execute(
        """
        CREATE TABLE research_graph_presentations (
            graph_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            locale TEXT NOT NULL,
            presentation_json TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (graph_id, version, locale)
        )
        """
    )
    rows = conn.execute(
        f"""
        SELECT old.*
        FROM "{legacy}" AS old
        WHERE old.translation_revision = (
            SELECT MAX(newer.translation_revision)
            FROM "{legacy}" AS newer
            WHERE newer.graph_id=old.graph_id
              AND newer.version=old.version
              AND newer.locale=old.locale
        )
        """
    ).fetchall()
    for row in rows:
        # Older rows could have embedded the presentation hash in the JSON as
        # well as in SQLite columns.  Strip that display-only identity during
        # the one-time collapse so it cannot reappear through the new API.
        presentation = orjson.loads(row["presentation_json"])
        if not isinstance(presentation, dict):
            raise ValueError("legacy research graph presentation is not an object")
        for field in (
            "content_hash", "translation_hash", "translation_revision",
            "created_by", "created_at",
        ):
            presentation.pop(field, None)
        conn.execute(
            """
            INSERT INTO research_graph_presentations (
                graph_id, version, locale, presentation_json, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(row["graph_id"]),
                int(row["version"]),
                str(row["locale"]),
                orjson.dumps(presentation, option=orjson.OPT_SORT_KEYS).decode(),
                str(row["created_by"]),
                float(row["created_at"]),
            ),
        )
    conn.execute(f'DROP TABLE "{legacy}"')


def _canonical_graph(graph: Mapping[str, Any]) -> dict[str, Any]:
    value = deepcopy(dict(graph))
    for field in (
        "created_by", "created_at", "active_pointer", "is_active",
        "presentation", "presentation_locale", "presentation_status",
    ):
        value.pop(field, None)
    return validate_graph(value)


def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
    value = orjson.loads(row["presentation_json"])
    if not isinstance(value, dict):
        raise ValueError("stored research graph presentation is not an object")
    for field in ("content_hash", "translation_hash", "translation_revision"):
        value.pop(field, None)
    value.update({
        "created_by": str(row["created_by"]),
        "created_at": float(row["created_at"]),
    })
    return value


__all__ = [
    "attach_presentation",
    "create_schema",
    "list_presentations",
    "load_presentation",
    "register_presentation",
]
