"""Canonical Work Package lifecycle with one row and bounded audit history."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

import orjson

import settings as Settings
from server.services.research_graph.report_checkpoint import (
    safe_identifier,
)
from tools.data.sqlite.db import connect_sqlite


LIFECYCLES = {"active", "archived", "deleted"}
ALLOWED_TRANSITIONS = {
    ("active", "archived"),
    ("archived", "active"),
    ("archived", "deleted"),
    ("deleted", "archived"),
}
NON_TERMINAL_JOBS = {
    "submitted",
    "planning",
    "awaiting_confirmation",
    "queued",
    "running",
    "paused",
}
MAX_LIFECYCLE_HISTORY = 32


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_work_packages (
            owner TEXT NOT NULL,
            work_package_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            lifecycle TEXT NOT NULL DEFAULT 'active' CHECK (
                lifecycle IN ('active', 'archived', 'deleted')
            ),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            lifecycle_history_json TEXT NOT NULL DEFAULT '[]',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            archived_at REAL,
            deleted_at REAL,
            PRIMARY KEY (owner, work_package_id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_work_packages_list
        ON research_work_packages(
            owner, workspace_id, lifecycle, updated_at DESC, work_package_id
        )
        """
    )


def backfill(conn: sqlite3.Connection) -> None:
    """Create canonical active rows for pre-lifecycle Work Packages."""
    conn.execute(
        """
        INSERT OR IGNORE INTO research_work_packages (
            owner, work_package_id, workspace_id, lifecycle, revision,
            lifecycle_history_json, created_at, updated_at
        )
        SELECT owner,
               COALESCE(NULLIF(work_package_id, ''), instance_id),
               workspace_id, 'active', 1, '[]',
               MIN(created_at), MAX(created_at)
        FROM research_graph_instances
        GROUP BY owner,
                 COALESCE(NULLIF(work_package_id, ''), instance_id),
                 workspace_id
        """
    )


def insert_active(
    conn: sqlite3.Connection,
    *,
    owner: str,
    work_package_id: str,
    workspace_id: str,
    created_at: float,
) -> None:
    conn.execute(
        """
        INSERT INTO research_work_packages (
            owner, work_package_id, workspace_id, lifecycle, revision,
            lifecycle_history_json, created_at, updated_at
        ) VALUES (?, ?, ?, 'active', 1, '[]', ?, ?)
        """,
        (owner, work_package_id, workspace_id, created_at, created_at),
    )


def transition_lifecycle(
    *,
    owner: str,
    work_package_ref: str,
    target: str,
    expected_revision: int,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    work_package_id = _parse_ref(work_package_ref)
    if target not in LIFECYCLES:
        raise ValueError("invalid Work Package lifecycle")
    if not actor.strip() or not reason.strip():
        raise ValueError("actor and reason are required")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM research_work_packages "
            "WHERE owner=? AND work_package_id=?",
            (owner, work_package_id),
        ).fetchone()
        if row is None:
            raise KeyError("work package not found")
        source = str(row["lifecycle"])
        if (source, target) not in ALLOWED_TRANSITIONS:
            raise ValueError(f"invalid lifecycle transition: {source} -> {target}")
        if int(row["revision"]) != int(expected_revision):
            raise ValueError("work package revision conflict")
        if target in {"archived", "deleted"}:
            live_job = _first_live_job(conn, owner, work_package_id)
            if live_job:
                raise ValueError(
                    f"work package has non-terminal job: {live_job}"
                )
        now = time.time()
        history = _history(row["lifecycle_history_json"])
        history.append({
            "from": source,
            "to": target,
            "actor": actor.strip(),
            "reason": reason.strip(),
            "at": now,
        })
        revision = int(row["revision"]) + 1
        conn.execute(
            """
            UPDATE research_work_packages
            SET lifecycle=?, revision=?, lifecycle_history_json=?,
                updated_at=?,
                archived_at=CASE
                    WHEN ?='archived' THEN ?
                    WHEN ?='active' THEN NULL
                    ELSE archived_at
                END,
                deleted_at=CASE
                    WHEN ?='deleted' THEN ?
                    WHEN ?='archived' THEN NULL
                    ELSE deleted_at
                END
            WHERE owner=? AND work_package_id=? AND revision=?
            """,
            (
                target,
                revision,
                orjson.dumps(history[-MAX_LIFECYCLE_HISTORY:]).decode(),
                now,
                target,
                now,
                target,
                target,
                now,
                target,
                owner,
                work_package_id,
                expected_revision,
            ),
        )
    return {
        "work_package_ref": f"work-package:{work_package_id}",
        "lifecycle": target,
        "revision": revision,
        "updated_at": now,
    }


def require_active(row: sqlite3.Row) -> None:
    lifecycle = str(row["work_package_lifecycle"] or "active")
    if lifecycle != "active":
        raise ValueError(f"work package is {lifecycle}")


def _history(value: str) -> list[dict[str, Any]]:
    parsed = orjson.loads(value or "[]")
    return [item for item in parsed if isinstance(item, dict)]


def _parse_ref(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("work-package:"):
        raise ValueError("work_package_ref must use work-package:<id>")
    identifier = safe_identifier(value.removeprefix("work-package:"))
    if not identifier:
        raise ValueError("work_package_ref is invalid")
    return identifier


def _first_live_job(
    conn: sqlite3.Connection,
    owner: str,
    work_package_id: str,
) -> str:
    tables = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('research_runs', 'research_jobs')"
        ).fetchall()
    }
    if tables != {"research_runs", "research_jobs"}:
        return ""
    placeholders = ",".join("?" for _ in NON_TERMINAL_JOBS)
    row = conn.execute(
        f"""
        SELECT job.job_id
        FROM research_jobs AS job
        JOIN research_runs AS run ON run.run_id=job.run_id
        JOIN research_graph_instances AS instance
          ON instance.instance_id=run.graph_instance_id
        WHERE instance.owner=?
          AND COALESCE(NULLIF(instance.work_package_id, ''),
                       instance.instance_id)=?
          AND job.status IN ({placeholders})
        LIMIT 1
        """,
        (owner, work_package_id, *sorted(NON_TERMINAL_JOBS)),
    ).fetchone()
    return str(row["job_id"]) if row is not None else ""
