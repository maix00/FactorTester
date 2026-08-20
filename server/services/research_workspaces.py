"""Durable research contexts; configuration lives in ResearchConfiguration."""

from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any

import settings as Settings
from server.services import research_configurations
from tools.data.sqlite.db import connect_sqlite


def _ensure_schema(conn: sqlite3.Connection) -> None:
    existing = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_workspaces'"
    ).fetchone()
    if existing is not None:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(research_workspaces)").fetchall()
        }
        if "current_revision" in columns or "factor_family_alias" in columns:
            raise RuntimeError(
                "legacy research workspace schema detected; run "
                "python -m tools.migrations.migrate_research_configurations --apply"
            )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_workspaces (
            workspace_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            deleted_at REAL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_workspaces_owner "
        "ON research_workspaces(owner, updated_at)"
    )


def _row_payload(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "workspace_id": str(row["workspace_id"]),
        "owner": str(row["owner"]),
        "kind": str(row["kind"]),
        "title": str(row["title"]),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def create_workspace(
    *, owner: str, title: str,
    factors: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace_id = uuid.uuid4().hex
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO research_workspaces (
                workspace_id, owner, kind, title, created_at, updated_at
            ) VALUES (?, ?, 'factor_research', ?, ?, ?)
            """,
            (workspace_id, owner, title, now, now),
        )
        row = conn.execute(
            "SELECT * FROM research_workspaces WHERE workspace_id=?", (workspace_id,)
        ).fetchone()
    workspace = _row_payload(row) or {}
    workspace["configuration"] = research_configurations.create_workspace_configuration(
        owner=owner,
        workspace_id=workspace_id,
        factors=factors,
        payload=payload,
    )
    return workspace


def load_workspace(*, workspace_id: str, owner: str) -> dict[str, Any] | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT * FROM research_workspaces
            WHERE workspace_id=? AND owner=? AND deleted_at IS NULL
            """,
            (workspace_id, owner),
        ).fetchone()
    workspace = _row_payload(row)
    if workspace is not None:
        workspace["configuration"] = research_configurations.load_workspace_configuration(
            workspace_id=workspace_id,
            owner=owner,
        )
    return workspace


def list_workspaces(*, owner: str) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT * FROM research_workspaces
            WHERE owner=? AND deleted_at IS NULL
            ORDER BY updated_at DESC, created_at DESC
            """,
            (owner,),
        ).fetchall()
    result = []
    for row in rows:
        workspace = _row_payload(row) or {}
        workspace["configuration"] = research_configurations.load_workspace_configuration(
            workspace_id=workspace["workspace_id"], owner=owner,
        )
        result.append(workspace)
    return result


def list_workspace_summaries(*, owner: str) -> list[dict[str, Any]]:
    """Return workspace identity rows without decoding every configuration.

    The authoring shell only needs these fields to populate its workspace
    selector.  The selected workspace configuration is loaded separately,
    keeping large factor/path payloads out of the initial page request.
    """
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT * FROM research_workspaces
            WHERE owner=? AND deleted_at IS NULL
            ORDER BY updated_at DESC, created_at DESC
            """,
            (owner,),
        ).fetchall()
    return [_row_payload(row) or {} for row in rows]


def delete_draft_workspace(*, workspace_id: str, owner: str) -> dict[str, Any] | None:
    """Delete tab-owned editable state without touching frozen evidence."""
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT workspace_id FROM research_workspaces "
            "WHERE workspace_id=? AND owner=? AND deleted_at IS NULL",
            (workspace_id, owner),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "DELETE FROM research_configurations WHERE workspace_id=? "
            "AND owner=? AND role='workspace'",
            (workspace_id, owner),
        )
        conn.execute(
            "DELETE FROM research_workspaces WHERE workspace_id=? AND owner=?",
            (workspace_id, owner),
        )
    return {"deleted": True}
