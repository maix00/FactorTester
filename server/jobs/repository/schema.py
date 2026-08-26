"""SQLite schema for canonical JobAttempt facts and retained artifacts."""

from __future__ import annotations

import sqlite3

import orjson

from server.services.maintenance_cases.schema import (
    create_schema as create_maintenance_schema,
)

from ..assurance import canonical_hash
from ..subjects import job_subjects


def index_job_subjects(
    conn: sqlite3.Connection, job_id: str, job_spec: object, *,
    include_formula_subjects: bool = True,
) -> None:
    """Replace one Job's derived object references transactionally."""
    identity = str(job_id)
    conn.execute("DELETE FROM research_job_subjects WHERE job_id=?", (identity,))
    conn.executemany(
        """INSERT INTO research_job_subjects(
               job_id, object_kind, object_ref, owner_ref, alias
           ) VALUES (?, ?, ?, ?, ?)""",
        [
            (
                identity, item.object_kind, item.object_ref,
                item.owner_ref, item.alias,
            )
            for item in job_subjects(
                job_spec, include_formula_subjects=include_formula_subjects,
            )
        ],
    )
    conn.execute(
        "INSERT OR REPLACE INTO research_job_subject_index_state(job_id) VALUES (?)",
        (identity,),
    )


def _backfill_job_subjects(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """SELECT jobs.job_id, jobs.job_spec_json
           FROM research_jobs AS jobs
           LEFT JOIN research_job_subject_index_state AS state
             ON state.job_id=jobs.job_id
           WHERE state.job_id IS NULL"""
    ).fetchall()
    for row in rows:
        try:
            payload = orjson.loads(row["job_spec_json"] or "{}")
        except (TypeError, ValueError, orjson.JSONDecodeError):
            payload = {}
        # Historical Jobs keep their original object-ref projection. Formula
        # subjects are admission-time facts for Jobs submitted after this
        # capability is installed, not a runtime compatibility backfill.
        index_job_subjects(
            conn, str(row["job_id"]), payload,
            include_formula_subjects=False,
        )


def ensure_job_schema(conn: sqlite3.Connection) -> None:
    legacy_assurance = conn.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='research_backend_assurance_receipts'
        """
    ).fetchone()
    if legacy_assurance is not None:
        raise RuntimeError(
            "legacy backend assurance requires the explicit "
            "migrate_backend_assurance cutover"
        )
    conn.executescript(
        """
        DROP TABLE IF EXISTS test_job_events;
        DROP TABLE IF EXISTS test_job_process_slots;
        DROP TABLE IF EXISTS test_job_artifacts;
        DROP TABLE IF EXISTS test_jobs;
        DROP TABLE IF EXISTS research_view_leases;

        CREATE TABLE IF NOT EXISTS research_jobs (
            job_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            owner TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            job_role TEXT NOT NULL DEFAULT 'primary',
            parent_job_id TEXT NOT NULL DEFAULT '',
            supplemental_kind TEXT NOT NULL DEFAULT '',
            supplemental_identity TEXT NOT NULL DEFAULT '',
            source_artifact_hash TEXT NOT NULL DEFAULT '',
            retry_of TEXT NOT NULL DEFAULT '',
            attempt INTEGER NOT NULL DEFAULT 1,
            step_mode INTEGER NOT NULL DEFAULT 0,
            retention_mode TEXT NOT NULL DEFAULT 'summary',
            deployment_id TEXT NOT NULL DEFAULT '',
            service_port INTEGER NOT NULL DEFAULT 0,
            source_revision TEXT NOT NULL DEFAULT '',
            runner_path TEXT NOT NULL DEFAULT '',
            job_spec_json TEXT NOT NULL,
            job_spec_hash TEXT NOT NULL,
            run_spec_hash TEXT NOT NULL DEFAULT '',
            worker_pid INTEGER,
            worker_exitcode INTEGER,
            cancel_requested_at REAL,
            cancel_reason TEXT NOT NULL DEFAULT '',
            entitlement_json TEXT NOT NULL,
            execution_plan_json TEXT,
            execution_plan_hash TEXT NOT NULL DEFAULT '',
            plan_notices_json TEXT NOT NULL DEFAULT '[]',
            result_summary_json TEXT,
            error_json TEXT,
            terminal_assurance_json TEXT,
            created_at REAL NOT NULL,
            planned_at REAL,
            approved_at REAL,
            queued_at REAL,
            started_at REAL,
            finished_at REAL,
            updated_at REAL NOT NULL,
            CHECK (status IN (
                'submitted', 'planning', 'awaiting_confirmation', 'queued',
                'running', 'paused', 'succeeded', 'failed', 'cancelled'
            )),
            CHECK (retention_mode IN ('summary', 'full')),
            CHECK (job_role IN ('primary', 'supplemental')),
            CHECK (
                (job_role='primary' AND parent_job_id=''
                 AND supplemental_kind='' AND supplemental_identity='')
                OR
                (job_role='supplemental' AND parent_job_id!=''
                 AND supplemental_kind!='' AND supplemental_identity!='')
            )
        );

        CREATE INDEX IF NOT EXISTS idx_research_jobs_owner_updated
            ON research_jobs(owner, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_research_jobs_global_updated
            ON research_jobs(updated_at DESC, job_id DESC);
        CREATE INDEX IF NOT EXISTS idx_research_jobs_workspace_updated
            ON research_jobs(owner, workspace_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_research_jobs_queue
            ON research_jobs(deployment_id, status, created_at);
        CREATE INDEX IF NOT EXISTS idx_research_jobs_run
            ON research_jobs(owner, run_id, created_at);

        CREATE TABLE IF NOT EXISTS research_job_subjects (
            job_id TEXT NOT NULL,
            object_kind TEXT NOT NULL,
            object_ref TEXT NOT NULL,
            owner_ref TEXT NOT NULL DEFAULT '',
            alias TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (job_id, object_kind, object_ref),
            FOREIGN KEY (job_id) REFERENCES research_jobs(job_id) ON DELETE CASCADE,
            CHECK (object_kind IN ('family', 'factor', 'set'))
        );
        CREATE INDEX IF NOT EXISTS idx_research_job_subject_ref
            ON research_job_subjects(object_kind, object_ref, job_id);
        CREATE INDEX IF NOT EXISTS idx_research_job_subject_alias
            ON research_job_subjects(object_kind, owner_ref, alias, job_id);
        CREATE TABLE IF NOT EXISTS research_job_subject_index_state (
            job_id TEXT PRIMARY KEY,
            FOREIGN KEY (job_id) REFERENCES research_jobs(job_id) ON DELETE CASCADE
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_research_jobs_one_active_step
            ON research_jobs(owner)
            WHERE step_mode=1 AND status IN (
                'submitted', 'planning', 'awaiting_confirmation',
                'queued', 'running', 'paused'
            );

        CREATE TABLE IF NOT EXISTS user_job_pins (
            owner TEXT PRIMARY KEY,
            job_id TEXT NOT NULL UNIQUE,
            pinned_at REAL NOT NULL,
            FOREIGN KEY (job_id) REFERENCES research_jobs(job_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_storage_policies (
            owner TEXT PRIMARY KEY,
            quota_bytes INTEGER NOT NULL,
            updated_at REAL NOT NULL,
            CHECK (quota_bytes >= 0)
        );

        CREATE TABLE IF NOT EXISTS research_job_artifacts (
            job_id TEXT NOT NULL,
            name TEXT NOT NULL,
            artifact_role TEXT NOT NULL DEFAULT 'output',
            artifact_kind TEXT NOT NULL DEFAULT '',
            file_name TEXT NOT NULL DEFAULT '',
            logical_path TEXT NOT NULL DEFAULT '',
            title_zh TEXT NOT NULL DEFAULT '',
            retention_mode TEXT NOT NULL,
            state TEXT NOT NULL,
            content_type TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at REAL NOT NULL,
            deleted_at REAL,
            PRIMARY KEY (job_id, name),
            FOREIGN KEY (job_id) REFERENCES research_jobs(job_id) ON DELETE CASCADE,
            CHECK (artifact_role IN ('input', 'output')),
            CHECK (retention_mode IN ('temporary', 'retained')),
            CHECK (state IN ('staging', 'active', 'deleting', 'deleted', 'failed')),
            CHECK (size_bytes >= 0)
        );

        CREATE TABLE IF NOT EXISTS research_job_custom_analyses (
            parent_job_id TEXT NOT NULL,
            tab_id TEXT NOT NULL,
            title TEXT NOT NULL,
            draft_source TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (parent_job_id, tab_id),
            FOREIGN KEY (parent_job_id) REFERENCES research_jobs(job_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_research_job_custom_analyses_updated
            ON research_job_custom_analyses(parent_job_id, updated_at DESC);

        """
    )
    create_maintenance_schema(conn)
    _backfill_job_subjects(conn)
    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(research_jobs)").fetchall()
    }
    if "run_spec_hash" not in columns:
        conn.execute(
            "ALTER TABLE research_jobs "
            "ADD COLUMN run_spec_hash TEXT NOT NULL DEFAULT ''"
        )
    if "terminal_assurance_json" not in columns:
        conn.execute(
            "ALTER TABLE research_jobs ADD COLUMN terminal_assurance_json TEXT"
        )
    if "service_port" not in columns:
        conn.execute(
            "ALTER TABLE research_jobs ADD COLUMN service_port INTEGER NOT NULL DEFAULT 0"
        )
    supplemental_columns = {
        "job_role", "parent_job_id", "supplemental_kind",
        "supplemental_identity", "source_artifact_hash",
    }
    missing_supplemental_columns = sorted(supplemental_columns - columns)
    if missing_supplemental_columns:
        raise RuntimeError(
            "research_jobs requires the explicit supplemental Job schema "
            "migration before startup; missing columns: "
            + ", ".join(missing_supplemental_columns)
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_jobs_parent_updated "
        "ON research_jobs(parent_job_id, updated_at DESC) "
        "WHERE job_role='supplemental'"
    )
    conn.execute("DROP INDEX IF EXISTS idx_research_jobs_supplemental_identity")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_research_jobs_supplemental_identity "
        "ON research_jobs(parent_job_id, supplemental_kind, "
        "supplemental_identity, source_artifact_hash) "
        "WHERE job_role='supplemental' "
        "AND status IN ('submitted', 'planning', 'queued', 'running', 'paused')"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_jobs_port_updated "
        "ON research_jobs(service_port, updated_at DESC)"
    )
    artifact_columns = {
        str(row["name"])
        for row in conn.execute(
            "PRAGMA table_info(research_job_artifacts)"
        ).fetchall()
    }
    for name, declaration in (
        ("artifact_role", "TEXT NOT NULL DEFAULT 'output'"),
        ("artifact_kind", "TEXT NOT NULL DEFAULT ''"),
        ("file_name", "TEXT NOT NULL DEFAULT ''"),
        ("logical_path", "TEXT NOT NULL DEFAULT ''"),
        ("title_zh", "TEXT NOT NULL DEFAULT ''"),
    ):
        if name not in artifact_columns:
            conn.execute(
                f"ALTER TABLE research_job_artifacts "
                f"ADD COLUMN {name} {declaration}"
            )
    active_without_run_hash = conn.execute(
        """
        SELECT job_id, job_spec_json
        FROM research_jobs
        WHERE run_spec_hash=''
          AND status IN (
              'submitted', 'planning', 'awaiting_confirmation',
              'queued', 'running', 'paused'
          )
        """
    ).fetchall()
    for row in active_without_run_hash:
        job_spec = orjson.loads(row["job_spec_json"])
        run_spec = job_spec.get("run_spec") if isinstance(job_spec, dict) else None
        if isinstance(run_spec, dict):
            conn.execute(
                """
                UPDATE research_jobs SET run_spec_hash=?
                WHERE job_id=? AND run_spec_hash=''
                """,
                (canonical_hash(run_spec), str(row["job_id"])),
            )
    unassured_terminal = conn.execute(
        """
        SELECT job_id FROM research_jobs
        WHERE status IN ('succeeded', 'failed', 'cancelled')
          AND terminal_assurance_json IS NULL
        LIMIT 1
        """
    ).fetchone()
    if unassured_terminal is not None:
        raise RuntimeError(
            "historical terminal Jobs require the explicit "
            "migrate_backend_assurance cutover"
        )
