"""Durable research workspace drafts and immutable revisions."""

from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any

import orjson

import settings as Settings
from tools.data.sqlite.db import connect_sqlite


SCHEMA_VERSION = 1


def _dumps(value: Any) -> str:
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS).decode()


def _loads(value: str | None) -> Any:
    return orjson.loads(value) if value else None


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_workspaces (
            workspace_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            factor_family_alias TEXT NOT NULL DEFAULT '',
            current_revision INTEGER NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            deleted_at REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_workspace_revisions (
            workspace_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            schema_version INTEGER NOT NULL,
            draft_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (workspace_id, revision)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_workspaces_owner "
        "ON research_workspaces(owner, updated_at)"
    )


def _row_payload(conn: sqlite3.Connection, row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    revision = int(row["current_revision"])
    revision_row = conn.execute(
        """
        SELECT schema_version, draft_json
        FROM research_workspace_revisions
        WHERE workspace_id = ? AND revision = ?
        """,
        (row["workspace_id"], revision),
    ).fetchone()
    return {
        "workspace_id": str(row["workspace_id"]),
        "owner": str(row["owner"]),
        "kind": str(row["kind"]),
        "title": str(row["title"]),
        "factor_family_alias": str(row["factor_family_alias"] or ""),
        "revision": revision,
        "schema_version": int(revision_row["schema_version"]),
        "draft": _loads(revision_row["draft_json"]) or {},
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def create_workspace(
    *,
    owner: str,
    kind: str,
    title: str,
    factor_family_alias: str = "",
    draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace_id = uuid.uuid4().hex
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO research_workspaces (
                workspace_id, owner, kind, title, factor_family_alias,
                current_revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (workspace_id, owner, kind, title, factor_family_alias, now, now),
        )
        conn.execute(
            """
            INSERT INTO research_workspace_revisions (
                workspace_id, revision, schema_version, draft_json, created_at
            ) VALUES (?, 1, ?, ?, ?)
            """,
            (workspace_id, SCHEMA_VERSION, _dumps(draft or {}), now),
        )
        row = conn.execute(
            "SELECT * FROM research_workspaces WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        return _row_payload(conn, row) or {}


def load_workspace(*, workspace_id: str, owner: str) -> dict[str, Any] | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT * FROM research_workspaces
            WHERE workspace_id = ? AND owner = ? AND deleted_at IS NULL
            """,
            (workspace_id, owner),
        ).fetchone()
        return _row_payload(conn, row)
