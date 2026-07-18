"""Immutable Graph versions and the read-only active pointer."""

from __future__ import annotations

from copy import deepcopy
import sqlite3
import time
from typing import Any

import orjson

import settings as Settings
from server.services.research_graph.protocol import (
    GraphVersionConflict,
    loads,
    validate_graph,
)
from tools.data.sqlite.db import connect_sqlite


_GRAPH_CACHE: dict[tuple[str, str, int, str], dict[str, Any]] = {}
_GRAPH_CACHE_INDEX: dict[tuple[str, str, int], str] = {}


def _version_cache_key(graph_id: str, version: int) -> tuple[str, str, int]:
    return (str(Settings.CACHE_DB_PATH), graph_id, int(version))


def _cache_graph(graph: dict[str, Any]) -> dict[str, Any]:
    graph_id = str(graph["graph_id"])
    version = int(graph["version"])
    content_hash = str(graph["content_hash"])
    version_key = _version_cache_key(graph_id, version)
    cache_key = (*version_key, content_hash)
    value = deepcopy(graph)
    _GRAPH_CACHE_INDEX[version_key] = content_hash
    _GRAPH_CACHE[cache_key] = value
    return deepcopy(value)


def _cached_graph(graph_id: str, version: int) -> dict[str, Any] | None:
    version_key = _version_cache_key(graph_id, version)
    content_hash = _GRAPH_CACHE_INDEX.get(version_key)
    if content_hash is None:
        return None
    value = _GRAPH_CACHE.get((*version_key, content_hash))
    return deepcopy(value) if value is not None else None


def clear_graph_cache_for_current_db() -> None:
    db_path = str(Settings.CACHE_DB_PATH)
    version_keys = [
        key for key in _GRAPH_CACHE_INDEX if key[0] == db_path
    ]
    for version_key in version_keys:
        content_hash = _GRAPH_CACHE_INDEX.pop(version_key)
        _GRAPH_CACHE.pop((*version_key, content_hash), None)


def _row_payload(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    graph = loads(row["graph_json"]) or {}
    graph["created_by"] = str(row["created_by"])
    graph["created_at"] = float(row["created_at"])
    return graph


def load_graph_from_conn(
    conn: sqlite3.Connection,
    *,
    graph_id: str,
    version: int,
) -> dict[str, Any] | None:
    cached = _cached_graph(graph_id, version)
    if cached is not None:
        return cached
    row = conn.execute(
        """
        SELECT * FROM research_graph_versions
        WHERE graph_id=? AND version=?
        """,
        (graph_id, int(version)),
    ).fetchone()
    graph = _row_payload(row)
    return _cache_graph(graph) if graph is not None else None


def insert_graph(
    conn: sqlite3.Connection,
    graph: dict[str, Any],
    *,
    actor: str,
) -> dict[str, Any]:
    value = validate_graph(graph)
    created_at = time.time()
    try:
        conn.execute(
            """
            INSERT INTO research_graph_versions (
                graph_id, version, lifecycle, parent_version, content_hash,
                graph_json, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                value["graph_id"],
                int(value["version"]),
                value["lifecycle"],
                int(value.get("parent_version") or 0),
                value["content_hash"],
                orjson.dumps(value, option=orjson.OPT_SORT_KEYS).decode(),
                actor,
                created_at,
            ),
        )
    except sqlite3.IntegrityError as exc:
        existing = conn.execute(
            """
            SELECT * FROM research_graph_versions
            WHERE graph_id=? AND version=?
            """,
            (value["graph_id"], int(value["version"])),
        ).fetchone()
        if (
            existing is not None
            and str(existing["content_hash"]) == value["content_hash"]
        ):
            return _cache_graph(_row_payload(existing) or {})
        raise GraphVersionConflict(
            f"graph version is immutable: {value['graph_id']} "
            f"v{value['version']}"
        ) from exc
    stored = deepcopy(value)
    stored["created_by"] = actor
    stored["created_at"] = created_at
    return _cache_graph(stored)


def register_graph(graph: dict[str, Any], *, actor: str) -> dict[str, Any]:
    value = validate_graph(graph)
    if value["lifecycle"] not in {"observed", "draft"}:
        raise ValueError("only observed or draft graphs may be registered")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        return insert_graph(conn, value, actor=actor)


def load_graph(*, graph_id: str, version: int) -> dict[str, Any] | None:
    cached = _cached_graph(graph_id, version)
    if cached is not None:
        return cached
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        return load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=version,
        )


def list_graph_versions(*, graph_id: str) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT * FROM research_graph_versions
            WHERE graph_id=? ORDER BY version
            """,
            (graph_id,),
        ).fetchall()
    return [_cache_graph(_row_payload(row) or {}) for row in rows]


def graph_lifecycle(
    conn: sqlite3.Connection,
    *,
    graph_id: str,
    version: int,
) -> str | None:
    row = conn.execute(
        """
        SELECT lifecycle FROM research_graph_versions
        WHERE graph_id=? AND version=?
        """,
        (graph_id, int(version)),
    ).fetchone()
    return str(row["lifecycle"]) if row is not None else None


def load_active_graph(*, graph_id: str) -> dict[str, Any] | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT version FROM active_research_graphs
            WHERE graph_id=?
            """,
            (graph_id,),
        ).fetchone()
        if row is None:
            return None
        return load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=int(row["version"]),
        )
