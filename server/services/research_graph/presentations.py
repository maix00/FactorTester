"""SQLite persistence and API projection for localized Graph presentations."""

from __future__ import annotations

from copy import deepcopy
import sqlite3
import time
from typing import Any, Mapping

import orjson

import settings as Settings
from server.services.research_graph.presentation_contract import (
    normalize_graph_locale,
    presentation_content_hash,
    validate_presentation,
)
from server.services.research_graph.protocol import validate_graph
from tools.data.sqlite.db import connect_sqlite


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_graph_presentations (
            graph_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            locale TEXT NOT NULL,
            translation_revision INTEGER NOT NULL,
            translation_hash TEXT NOT NULL,
            presentation_json TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (graph_id, version, locale, translation_revision),
            UNIQUE (graph_id, version, locale, translation_hash)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_graph_presentations_latest
        ON research_graph_presentations(graph_id, version, locale, translation_revision DESC)
        """
    )


def register_presentation(
    graph: Mapping[str, Any],
    presentation: Mapping[str, Any],
    *,
    actor: str,
) -> dict[str, Any]:
    """Insert an immutable translation revision, idempotently by content hash."""
    canonical = _canonical_graph(graph)
    normalized = validate_presentation(canonical, presentation)
    translation_hash = presentation_content_hash(normalized)
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        # Revision numbers are immutable per (Graph version, locale).  Take
        # the write lock before reading MAX so two curators cannot allocate
        # the same revision concurrently.
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            """
            SELECT * FROM research_graph_presentations
            WHERE graph_id=? AND version=? AND locale=? AND translation_hash=?
            """,
            (
                canonical["graph_id"],
                int(canonical["version"]),
                normalized["locale"],
                translation_hash,
            ),
        ).fetchone()
        if existing is not None:
            return _row_payload(existing)
        row = conn.execute(
            """
            SELECT COALESCE(MAX(translation_revision), 0) + 1 AS next_revision
            FROM research_graph_presentations
            WHERE graph_id=? AND version=? AND locale=?
            """,
            (
                canonical["graph_id"],
                int(canonical["version"]),
                normalized["locale"],
            ),
        ).fetchone()
        revision = int(row["next_revision"])
        conn.execute(
            """
            INSERT INTO research_graph_presentations (
                graph_id, version, locale, translation_revision,
                translation_hash, presentation_json, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical["graph_id"],
                int(canonical["version"]),
                normalized["locale"],
                revision,
                translation_hash,
                orjson.dumps(normalized, option=orjson.OPT_SORT_KEYS).decode(),
                str(actor),
                now,
            ),
        )
        stored = deepcopy(normalized)
        stored.update({
            "translation_revision": revision,
            "translation_hash": translation_hash,
            "created_by": str(actor),
            "created_at": now,
        })
        return stored


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
            ORDER BY translation_revision DESC
            LIMIT 1
            """,
            (graph_id, int(version), normalized_locale),
        ).fetchone()
    return _row_payload(row) if row is not None else None


def list_presentations(*, graph_id: str, version: int) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT * FROM research_graph_presentations
            WHERE graph_id=? AND version=?
            ORDER BY locale, translation_revision DESC
            """,
            (graph_id, int(version)),
        ).fetchall()
    return [_row_payload(row) for row in rows]


def attach_presentation(
    graph: Mapping[str, Any],
    *,
    locale: str | None,
) -> dict[str, Any]:
    """Attach read-only localized display data without altering Graph identity."""
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


def _canonical_graph(graph: Mapping[str, Any]) -> dict[str, Any]:
    value = deepcopy(dict(graph))
    for field in (
        "created_by",
        "created_at",
        "active_pointer",
        "is_active",
        "presentation",
        "presentation_locale",
        "presentation_status",
    ):
        value.pop(field, None)
    return validate_graph(value)


def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
    value = orjson.loads(row["presentation_json"])
    if not isinstance(value, dict):
        raise ValueError("stored research graph presentation is not an object")
    value.update({
        "translation_revision": int(row["translation_revision"]),
        "translation_hash": str(row["translation_hash"]),
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
