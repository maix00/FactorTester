"""Immutable research runs created from workspace revisions."""

from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from typing import Any

import orjson

import settings as Settings
from tools.data.sqlite.db import connect_sqlite


RUN_SPEC_VERSION = 1


def _loads(value: str | None) -> Any:
    return orjson.loads(value) if value else None


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_runs (
            run_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            workspace_revision INTEGER NOT NULL,
            kind TEXT NOT NULL,
            lifecycle_policy TEXT NOT NULL,
            run_spec_version INTEGER NOT NULL,
            run_spec_hash TEXT NOT NULL,
            run_spec_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_runs_owner_workspace "
        "ON research_runs(owner, workspace_id, created_at)"
    )


def create_run(
    *,
    owner: str,
    workspace_id: str,
    workspace_revision: int,
    lifecycle_policy: str,
    run_spec: dict[str, Any],
) -> dict[str, Any]:
    run_id = uuid.uuid4().hex
    raw = orjson.dumps(run_spec, option=orjson.OPT_SORT_KEYS)
    created_at = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO research_runs (
                run_id, owner, workspace_id, workspace_revision, kind,
                lifecycle_policy, run_spec_version, run_spec_hash,
                run_spec_json, created_at
            ) VALUES (?, ?, ?, ?, 'single_factor', ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                owner,
                workspace_id,
                int(workspace_revision),
                lifecycle_policy,
                RUN_SPEC_VERSION,
                hashlib.sha256(raw).hexdigest(),
                raw.decode(),
                created_at,
            ),
        )
    return load_run(run_id=run_id, owner=owner) or {}


def load_run(*, run_id: str, owner: str) -> dict[str, Any] | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM research_runs WHERE run_id = ? AND owner = ?",
            (run_id, owner),
        ).fetchone()
    if row is None:
        return None
    return {
        "run_id": str(row["run_id"]),
        "owner": str(row["owner"]),
        "workspace_id": str(row["workspace_id"]),
        "workspace_revision": int(row["workspace_revision"]),
        "kind": str(row["kind"]),
        "lifecycle_policy": str(row["lifecycle_policy"]),
        "run_spec_version": int(row["run_spec_version"]),
        "run_spec_hash": str(row["run_spec_hash"]),
        "run_spec": _loads(row["run_spec_json"]) or {},
        "created_at": float(row["created_at"]),
    }
