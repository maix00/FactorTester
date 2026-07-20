"""TrialPlan stage projection schema upgrade tests."""

from __future__ import annotations

import settings as Settings
from server.services import research_runs
from server.services.research_graph.branch.schema import (
    ensure_instance_branch_schema,
)
from tools.data.sqlite.db import connect_sqlite


def test_existing_target_branch_gains_stage_projection_without_row_loss(
    tmp_path,
) -> None:
    path = tmp_path / "stage-schema.sqlite"
    with connect_sqlite(path) as conn:
        conn.executescript(
            """
            CREATE TABLE research_graph_branches (
                branch_id TEXT PRIMARY KEY,
                instance_id TEXT NOT NULL,
                label TEXT NOT NULL,
                current_node TEXT NOT NULL,
                status TEXT NOT NULL,
                current_capability_resolution_json TEXT NOT NULL,
                current_capability_resolution_hash TEXT NOT NULL,
                current_trial_plan_hash TEXT NOT NULL DEFAULT '',
                evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                omitted_evidence_count INTEGER NOT NULL DEFAULT 0,
                latest_trace_id TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO research_graph_branches (
                branch_id, instance_id, label, current_node, status,
                current_capability_resolution_json,
                current_capability_resolution_hash,
                current_trial_plan_hash, created_at, updated_at
            ) VALUES (
                'branch-1', 'instance-1', 'primary', 'validation_design',
                'running', '{}', '', ?, 1, 2
            )
            """,
            ("a" * 64,),
        )

        ensure_instance_branch_schema(conn)

        row = conn.execute(
            """
            SELECT branch_id, current_trial_plan_hash,
                   trial_stage_projection_json
            FROM research_graph_branches
            """
        ).fetchone()

    assert dict(row) == {
        "branch_id": "branch-1",
        "current_trial_plan_hash": "a" * 64,
        "trial_stage_projection_json": "{}",
    }


def test_existing_research_run_gains_server_derived_stage_without_row_loss(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "run-stage-schema.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    with connect_sqlite(path) as conn:
        conn.executescript(
            """
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
                graph_instance_id TEXT NOT NULL DEFAULT '',
                graph_branch_id TEXT NOT NULL DEFAULT '',
                sample_ref TEXT NOT NULL DEFAULT '',
                sample_hash TEXT NOT NULL DEFAULT '',
                sample_identity_hash TEXT NOT NULL DEFAULT '',
                sample_start TEXT NOT NULL DEFAULT '',
                sample_end TEXT NOT NULL DEFAULT '',
                sample_universe_hash TEXT NOT NULL DEFAULT '',
                sample_design_context_hash TEXT NOT NULL DEFAULT '',
                sample_identity_assurance TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );
            INSERT INTO research_runs (
                run_id, owner, workspace_id, configuration_id,
                configuration_revision, kind, run_spec_version,
                run_spec_hash, run_spec_json, created_at
            ) VALUES (
                'run-1', 'alice', 'workspace-1', 'config-1', 1,
                'factor_research', 1, 'hash-1', '{}', 1
            );
            """
        )

    research_runs.ensure_schema()

    with connect_sqlite(path) as conn:
        columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(research_runs)"
            ).fetchall()
        }
        row = conn.execute(
            "SELECT run_id, trial_stage FROM research_runs"
        ).fetchone()

    assert "trial_stage" in columns
    assert dict(row) == {"run_id": "run-1", "trial_stage": ""}
