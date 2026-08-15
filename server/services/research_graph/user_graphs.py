"""Owner-scoped Research Graph YAML files.

These files are a user library, not published server Graph versions.  A
published Graph keeps the protocol's semantic ``content_hash`` because it is
part of execution identity.  User files intentionally have no second content
hash, revision chain, approval record, or activation side effect.
"""

from __future__ import annotations

import os
from pathlib import PurePath
import re
import sqlite3
import time
from typing import Any, Mapping
import uuid

import orjson
import yaml

import settings as Settings
from server.services.research_graph.protocol import validate_graph
from tools.data.sqlite.db import connect_sqlite


MAX_USER_GRAPH_YAML_BYTES = 2 * 1024 * 1024
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_SERVER_ID = str(os.environ.get("FACTORTESTER_SERVER_ID") or "local").strip()


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the small local library and preference tables."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_research_graphs (
            graph_file_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            name TEXT NOT NULL,
            filename TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            graph_version INTEGER NOT NULL,
            graph_json TEXT NOT NULL,
            yaml_text TEXT NOT NULL,
            source_server_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_user_research_graphs_owner
            ON user_research_graphs(owner, updated_at DESC);
        CREATE TABLE IF NOT EXISTS user_research_graph_preferences (
            owner TEXT PRIMARY KEY,
            default_kind TEXT NOT NULL,
            default_ref TEXT NOT NULL,
            updated_at REAL NOT NULL
        );
        """
    )


def upload_graph(
    *,
    owner: str,
    filename: str,
    raw_yaml: bytes | str,
    name: str = "",
) -> dict[str, Any]:
    """Validate once, normalize, and store one private user Graph file."""
    owner = _required(owner, "owner")
    filename = _safe_filename(filename)
    text = _decode_yaml(raw_yaml)
    graph = _parse_graph(text)
    now = time.time()
    file_id = uuid.uuid4().hex
    display_name = _display_name(name, filename, graph)
    canonical_yaml = yaml.safe_dump(
        graph,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=True,
        width=120,
    )
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO user_research_graphs (
                graph_file_id, owner, name, filename, graph_id, graph_version,
                graph_json, yaml_text, source_server_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                owner,
                display_name,
                filename,
                str(graph["graph_id"]),
                int(graph["version"]),
                orjson.dumps(graph, option=orjson.OPT_SORT_KEYS).decode(),
                canonical_yaml,
                _SERVER_ID,
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM user_research_graphs WHERE graph_file_id=?",
            (file_id,),
        ).fetchone()
    return _metadata(row, is_default=False)


def list_graphs(*, owner: str) -> list[dict[str, Any]]:
    owner = _required(owner, "owner")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT * FROM user_research_graphs
            WHERE owner=? ORDER BY updated_at DESC, graph_file_id
            """,
            (owner,),
        ).fetchall()
        preference = conn.execute(
            """
            SELECT default_ref FROM user_research_graph_preferences
            WHERE owner=?
            """,
            (owner,),
        ).fetchone()
    default_ref = str(preference["default_ref"]) if preference else ""
    return [
        _metadata(row, is_default=str(row["graph_file_id"]) == default_ref)
        for row in rows
    ]


def load_graph_file(*, owner: str, graph_file_id: str) -> dict[str, Any] | None:
    owner = _required(owner, "owner")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT * FROM user_research_graphs
            WHERE owner=? AND graph_file_id=?
            """,
            (owner, str(graph_file_id)),
        ).fetchone()
    if row is None:
        return None
    default_ref = _current_default_ref(owner)
    return {
        **_metadata(
            row,
            is_default=default_ref == str(graph_file_id),
        ),
        "graph": orjson.loads(row["graph_json"]),
        "yaml": str(row["yaml_text"]),
    }


def delete_graph(*, owner: str, graph_file_id: str) -> bool:
    owner = _required(owner, "owner")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        deleted = conn.execute(
            "DELETE FROM user_research_graphs WHERE owner=? AND graph_file_id=?",
            (owner, str(graph_file_id)),
        ).rowcount
        preference = conn.execute(
            """
            SELECT default_ref FROM user_research_graph_preferences
            WHERE owner=?
            """,
            (owner,),
        ).fetchone()
        if preference is not None and str(preference["default_ref"]) == str(
            graph_file_id
        ):
            conn.execute(
                "DELETE FROM user_research_graph_preferences WHERE owner=?",
                (owner,),
            )
    return bool(deleted)


def _current_default_ref(owner: str) -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = conn.execute(
            "SELECT default_ref FROM user_research_graph_preferences WHERE owner=?",
            (owner,),
        ).fetchone()
    return str(row["default_ref"]) if row is not None else ""


def _parse_graph(text: str) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"research graph YAML is invalid: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("research graph YAML must contain an object")
    # A locale bundle downloaded from the server is also a valid input.  The
    # private library stores the executable Graph part, not a second display
    # presentation identity.
    candidate = payload.get("graph") if isinstance(payload.get("graph"), Mapping) else payload
    candidate = dict(candidate)
    # User files are semantic Graph documents, not locale bundles.  Do not
    # persist a language marker even when a hand-authored file contains one;
    # the server-managed presentation table is the only place where locale is
    # recorded.
    for field in (
        "locale", "language", "language_version", "presentation_locale",
        "presentation", "translations",
    ):
        candidate.pop(field, None)
    # Recompute the one semantic identity during upload.  A stale downloaded
    # hash must not make a personal file impossible to import.
    candidate.pop("content_hash", None)
    try:
        return validate_graph(candidate)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"research graph YAML is not a valid Graph: {exc}") from exc


def _decode_yaml(raw_yaml: bytes | str) -> str:
    if isinstance(raw_yaml, bytes):
        if len(raw_yaml) > MAX_USER_GRAPH_YAML_BYTES:
            raise ValueError("research graph YAML exceeds 2 MiB")
        try:
            text = raw_yaml.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("research graph YAML must be UTF-8") from exc
    elif isinstance(raw_yaml, str):
        text = raw_yaml
        if len(text.encode("utf-8")) > MAX_USER_GRAPH_YAML_BYTES:
            raise ValueError("research graph YAML exceeds 2 MiB")
    else:
        raise TypeError("research graph YAML must be bytes or text")
    if not text.strip():
        raise ValueError("research graph YAML is empty")
    return text


def _metadata(row: sqlite3.Row, *, is_default: bool) -> dict[str, Any]:
    return {
        "graph_file_id": str(row["graph_file_id"]),
        "owner": str(row["owner"]),
        "name": str(row["name"]),
        "filename": str(row["filename"]),
        "graph_id": str(row["graph_id"]),
        "version": int(row["graph_version"]),
        "source_server_id": str(row["source_server_id"]),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "is_default": bool(is_default),
        "sync_scope": "manager-local",
    }


def _safe_filename(value: str) -> str:
    raw = PurePath(str(value or "research-graph.yaml")).name
    cleaned = _SAFE_FILENAME.sub("-", raw).strip(".-") or "research-graph"
    if not cleaned.lower().endswith((".yaml", ".yml")):
        cleaned += ".yaml"
    return cleaned[:160]


def _display_name(value: str, filename: str, graph: Mapping[str, Any]) -> str:
    raw = str(value or "").strip()
    if not raw:
        raw = PurePath(filename).stem or str(graph.get("graph_id") or "research-graph")
    return raw[:120]


def _required(value: str, field: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    return value


__all__ = [
    "MAX_USER_GRAPH_YAML_BYTES",
    "create_schema",
    "delete_graph",
    "list_graphs",
    "load_graph_file",
    "upload_graph",
]
