"""Immutable research runs created from canonical configurations."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from typing import Any

import orjson

import settings as Settings
from server.services.research_graph.trial_plan.binding import (
    normalize_run_binding,
    validate_branch_binding,
)
from tools.data.sqlite.db import connect_sqlite


RUN_SPEC_VERSION = 1
_SCHEMA_READY_PATHS: set[str] = set()
_SCHEMA_LOCK = threading.Lock()


def _loads(value: str | None) -> Any:
    return orjson.loads(value) if value else None


def _ensure_schema(conn: sqlite3.Connection) -> None:
    existing = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_runs'"
    ).fetchone()
    if existing is not None:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(research_runs)").fetchall()
        }
        if "configuration_id" not in columns:
            raise RuntimeError(
                "legacy research run schema detected; run "
                "python -m tools.migrations.migrate_research_configurations --apply"
            )
        if "lifecycle_policy" in columns:
            conn.executescript(
                """
                ALTER TABLE research_runs RENAME TO research_runs_with_lifecycle;
                CREATE TABLE research_runs (
                    run_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    configuration_id TEXT NOT NULL,
                    configuration_revision INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    run_spec_version INTEGER NOT NULL,
                    run_spec_hash TEXT NOT NULL,
                    run_spec_json TEXT NOT NULL,
                    trial_plan_id TEXT NOT NULL DEFAULT '',
                    trial_plan_hash TEXT NOT NULL DEFAULT '',
                    trial_plan_version INTEGER NOT NULL DEFAULT 0,
                    trial_role TEXT NOT NULL DEFAULT '',
                    comparison_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
                INSERT INTO research_runs (
                    run_id, owner, workspace_id, configuration_id,
                    configuration_revision, kind, run_spec_version,
                    run_spec_hash, run_spec_json, created_at
                )
                SELECT run_id, owner, workspace_id, configuration_id,
                       configuration_revision, kind, run_spec_version,
                       run_spec_hash, run_spec_json, created_at
                FROM research_runs_with_lifecycle;
                DROP TABLE research_runs_with_lifecycle;
                """
            )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_runs (
            run_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            configuration_id TEXT NOT NULL,
            configuration_revision INTEGER NOT NULL,
            kind TEXT NOT NULL,
            run_spec_version INTEGER NOT NULL,
            run_spec_hash TEXT NOT NULL,
            run_spec_json TEXT NOT NULL,
            trial_plan_id TEXT NOT NULL DEFAULT '',
            trial_plan_hash TEXT NOT NULL DEFAULT '',
            trial_plan_version INTEGER NOT NULL DEFAULT 0,
            trial_role TEXT NOT NULL DEFAULT '',
            comparison_id TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        )
        """
    )
    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(research_runs)").fetchall()
    }
    additions = (
        ("trial_plan_id", "TEXT NOT NULL DEFAULT ''"),
        ("trial_plan_hash", "TEXT NOT NULL DEFAULT ''"),
        ("trial_plan_version", "INTEGER NOT NULL DEFAULT 0"),
        ("trial_role", "TEXT NOT NULL DEFAULT ''"),
        ("comparison_id", "TEXT NOT NULL DEFAULT ''"),
    )
    for column, declaration in additions:
        if column not in columns:
            conn.execute(
                f"ALTER TABLE research_runs ADD COLUMN {column} {declaration}"
            )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_runs_owner_workspace "
        "ON research_runs(owner, workspace_id, created_at)"
    )


def _connect() -> sqlite3.Connection:
    path = str(Path(Settings.CACHE_DB_PATH))
    conn = connect_sqlite(Settings.CACHE_DB_PATH)
    if path not in _SCHEMA_READY_PATHS:
        with _SCHEMA_LOCK:
            if path not in _SCHEMA_READY_PATHS:
                try:
                    _ensure_schema(conn)
                except Exception:
                    conn.close()
                    raise
                _SCHEMA_READY_PATHS.add(path)
    return conn


def ensure_schema() -> None:
    with _connect():
        pass


def create_run(
    *, owner: str, workspace_id: str, configuration_id: str,
    configuration_revision: int, run_spec: dict[str, Any],
    trial_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = uuid.uuid4().hex
    raw = orjson.dumps(run_spec, option=orjson.OPT_SORT_KEYS)
    run_spec_hash = hashlib.sha256(raw).hexdigest()
    binding = _normalize_trial_binding(
        trial_binding,
        run_spec_hash=run_spec_hash,
    )
    persisted_binding = dict(binding or {})
    created_at = time.time()
    with _connect() as conn:
        if binding is not None:
            validate_branch_binding(
                conn,
                owner=owner,
                workspace_id=workspace_id,
                instance_id=str(binding["instance_id"]),
                branch_id=str(binding["branch_id"]),
                trial_plan_hash=binding["trial_plan_hash"],
            )
        conn.execute(
            """
            INSERT INTO research_runs (
                run_id, owner, workspace_id, configuration_id,
                configuration_revision, kind, run_spec_version,
                run_spec_hash, run_spec_json, trial_plan_id, trial_plan_hash,
                trial_plan_version, trial_role, comparison_id, created_at
            ) VALUES (
                ?, ?, ?, ?, ?, 'factor_research', ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                run_id, owner, workspace_id, configuration_id,
                int(configuration_revision), RUN_SPEC_VERSION,
                run_spec_hash, raw.decode(),
                str((binding or {}).get("trial_plan_id") or ""),
                str((binding or {}).get("trial_plan_hash") or ""),
                int((binding or {}).get("trial_plan_version") or 0),
                str((binding or {}).get("trial_role") or ""),
                str((binding or {}).get("comparison_id") or ""),
                created_at,
            ),
        )
    return {
        "run_id": run_id,
        "owner": owner,
        "workspace_id": workspace_id,
        "configuration_id": configuration_id,
        "configuration_revision": int(configuration_revision),
        "kind": "factor_research",
        "run_spec_version": RUN_SPEC_VERSION,
        "run_spec_hash": run_spec_hash,
        "run_spec": deepcopy(run_spec),
        "trial_plan_id": str(
            persisted_binding.get("trial_plan_id") or ""
        ),
        "trial_plan_hash": str(
            persisted_binding.get("trial_plan_hash") or ""
        ),
        "trial_plan_version": int(
            persisted_binding.get("trial_plan_version") or 0
        ),
        "trial_role": str(persisted_binding.get("trial_role") or ""),
        "comparison_id": str(
            persisted_binding.get("comparison_id") or ""
        ),
        "created_at": created_at,
    }


def load_run(*, run_id: str, owner: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM research_runs WHERE run_id=? AND owner=?", (run_id, owner)
        ).fetchone()
    if row is None:
        return None
    return {
        "run_id": str(row["run_id"]),
        "owner": str(row["owner"]),
        "workspace_id": str(row["workspace_id"]),
        "configuration_id": str(row["configuration_id"]),
        "configuration_revision": int(row["configuration_revision"]),
        "kind": str(row["kind"]),
        "run_spec_version": int(row["run_spec_version"]),
        "run_spec_hash": str(row["run_spec_hash"]),
        "run_spec": _loads(row["run_spec_json"]) or {},
        "trial_plan_id": str(row["trial_plan_id"]),
        "trial_plan_hash": str(row["trial_plan_hash"]),
        "trial_plan_version": int(row["trial_plan_version"]),
        "trial_role": str(row["trial_role"]),
        "comparison_id": str(row["comparison_id"]),
        "created_at": float(row["created_at"]),
    }


def load_job_trial_binding(
    *,
    job_id: str,
    owner: str,
) -> dict[str, Any] | None:
    """Project a JobAttempt's immutable binding from its owning ResearchRun."""
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT runs.trial_plan_id, runs.trial_plan_hash,
                       runs.trial_plan_version, runs.trial_role,
                       runs.comparison_id
                FROM research_jobs AS jobs
                JOIN research_runs AS runs ON runs.run_id=jobs.run_id
                WHERE jobs.job_id=? AND jobs.owner=? AND runs.owner=?
                """,
                (job_id, owner, owner),
            ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table: research_jobs" not in str(exc):
            raise
        return None
    if row is None:
        return None
    if not str(row["trial_plan_hash"]):
        return None
    return {
        "trial_plan_id": str(row["trial_plan_id"]),
        "trial_plan_hash": str(row["trial_plan_hash"]),
        "trial_plan_version": int(row["trial_plan_version"]),
        "trial_role": str(row["trial_role"]),
        "comparison_id": str(row["comparison_id"]),
    }


def _normalize_trial_binding(
    value: dict[str, Any] | None,
    *,
    run_spec_hash: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("trial_binding must be an object")
    required = {
        "instance_id",
        "branch_id",
        "trial_plan",
        "trial_plan_hash",
        "trial_plan_version",
        "trial_role",
        "comparison_id",
    }
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required)
    if missing:
        raise ValueError(
            "trial_binding missing fields: " + ", ".join(missing)
        )
    if extra:
        raise ValueError(
            "trial_binding has unsupported fields: " + ", ".join(extra)
        )
    instance_id = str(value["instance_id"] or "").strip()
    branch_id = str(value["branch_id"] or "").strip()
    if not instance_id or not branch_id:
        raise ValueError("trial_binding requires instance_id and branch_id")
    binding = normalize_run_binding(
        trial_plan=value["trial_plan"],
        expected_hash=str(value["trial_plan_hash"]),
        expected_version=value["trial_plan_version"],
        run_spec_hash=run_spec_hash,
        trial_role=str(value["trial_role"]),
        comparison_id=str(value["comparison_id"]),
    )
    return {
        "instance_id": instance_id,
        "branch_id": branch_id,
        **binding,
    }
