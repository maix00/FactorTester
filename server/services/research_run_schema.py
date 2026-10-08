"""Cold-path schema for immutable factor ResearchRuns."""

from __future__ import annotations

import sqlite3


_RETIRED_RUN_COLUMNS = (
    "graph_instance_id",
    "graph_branch_id",
    "graph_execution_node",
    "trial_stage_id",
    "decision_contract_hash",
    "methodology_hash",
    "evidence_action_id",
    "evidence_action_binding_hash",
    "evidence_action_binding_json",
)
_RETIRED_INDEXES = (
    "idx_research_runs_owner_graph_branch",
    "idx_research_runs_action_member",
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    existing = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_runs'"
    ).fetchone()
    if existing is not None:
        columns = _columns(conn)
        if "configuration_id" not in columns:
            raise RuntimeError(
                "legacy research run schema detected; run "
                "python -m tools.migrations.migrate_research_configurations --apply"
            )
        if "lifecycle_policy" in columns:
            _remove_legacy_lifecycle(conn)
        retired = columns.intersection(_RETIRED_RUN_COLUMNS)
        if retired:
            raise RuntimeError(
                "retired Run columns require the backed-up schema cutover "
                "before this server can start: " + ", ".join(sorted(retired))
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
            trial_plan_schema_version INTEGER NOT NULL DEFAULT 0,
            trial_plan_version INTEGER NOT NULL DEFAULT 0,
            trial_role TEXT NOT NULL DEFAULT '',
            trial_stage TEXT NOT NULL DEFAULT '',
            comparison_id TEXT NOT NULL DEFAULT '',
            sample_ref TEXT NOT NULL DEFAULT '',
            sample_hash TEXT NOT NULL DEFAULT '',
            sample_identity_hash TEXT NOT NULL DEFAULT '',
            sample_start TEXT NOT NULL DEFAULT '',
            sample_end TEXT NOT NULL DEFAULT '',
            sample_universe_hash TEXT NOT NULL DEFAULT '',
            sample_universe_members_json TEXT NOT NULL DEFAULT '',
            sample_design_context_hash TEXT NOT NULL DEFAULT '',
            sample_identity_assurance TEXT NOT NULL DEFAULT '',
            sample_use_json TEXT NOT NULL DEFAULT '{}',
            sample_use_hash TEXT NOT NULL DEFAULT '',
            report_binding_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL
        )
        """
    )
    columns = _columns(conn)
    additions = (
        ("trial_plan_id", "TEXT NOT NULL DEFAULT ''"),
        ("trial_plan_hash", "TEXT NOT NULL DEFAULT ''"),
        ("trial_plan_schema_version", "INTEGER NOT NULL DEFAULT 0"),
        ("trial_plan_version", "INTEGER NOT NULL DEFAULT 0"),
        ("trial_role", "TEXT NOT NULL DEFAULT ''"),
        ("trial_stage", "TEXT NOT NULL DEFAULT ''"),
        ("comparison_id", "TEXT NOT NULL DEFAULT ''"),
        ("sample_ref", "TEXT NOT NULL DEFAULT ''"),
        ("sample_hash", "TEXT NOT NULL DEFAULT ''"),
        ("sample_identity_hash", "TEXT NOT NULL DEFAULT ''"),
        ("sample_start", "TEXT NOT NULL DEFAULT ''"),
        ("sample_end", "TEXT NOT NULL DEFAULT ''"),
        ("sample_universe_hash", "TEXT NOT NULL DEFAULT ''"),
        ("sample_universe_members_json", "TEXT NOT NULL DEFAULT ''"),
        ("sample_design_context_hash", "TEXT NOT NULL DEFAULT ''"),
        ("sample_identity_assurance", "TEXT NOT NULL DEFAULT ''"),
        ("sample_use_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("sample_use_hash", "TEXT NOT NULL DEFAULT ''"),
        ("report_binding_json", "TEXT NOT NULL DEFAULT '{}'"),
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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_runs_owner_sample_scope "
        "ON research_runs(owner, sample_universe_hash, sample_start, sample_end)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_runs_owner_sample_dates "
        "ON research_runs(owner, sample_start, sample_end)"
    )


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(research_runs)").fetchall()
    }


def _remove_legacy_lifecycle(conn: sqlite3.Connection) -> None:
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
