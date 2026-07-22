"""TrialPlan stage projection schema upgrade tests."""

from __future__ import annotations

import json

import pytest

import settings as Settings
from server.services import research_runs
from server.services.research_graph.branch.schema import (
    ensure_instance_branch_schema,
)
from tools.data.sqlite.db import connect_sqlite


def _create_pre_identity_graph_schema(conn, *, source_branch: str) -> None:
    conn.executescript(
        """
        CREATE TABLE research_graph_instances (
            instance_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
            graph_id TEXT NOT NULL, graph_version INTEGER NOT NULL,
            product_group TEXT NOT NULL, workspace_id TEXT NOT NULL,
            mode TEXT NOT NULL, shadow_run_id TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE research_graph_branches (
            branch_id TEXT PRIMARY KEY, instance_id TEXT NOT NULL,
            label TEXT NOT NULL, current_node TEXT NOT NULL,
            status TEXT NOT NULL,
            current_capability_resolution_json TEXT NOT NULL,
            current_capability_resolution_hash TEXT NOT NULL,
            current_trial_plan_hash TEXT NOT NULL DEFAULT '',
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            omitted_evidence_count INTEGER NOT NULL DEFAULT 0,
            latest_trace_id TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE TABLE research_graph_trace (
            trace_id TEXT PRIMARY KEY, instance_id TEXT NOT NULL,
            branch_id TEXT NOT NULL, edge_id TEXT NOT NULL,
            from_node TEXT NOT NULL, to_node TEXT NOT NULL,
            evidence_json TEXT NOT NULL, telemetry_json TEXT NOT NULL,
            actor TEXT NOT NULL, created_at REAL NOT NULL
        );
        INSERT INTO research_graph_instances VALUES
            ('instance-v6', 'alice', 'factor-research', 6, 'CNFutures',
             'workspace-a', 'live', '', 1),
            ('instance-v7', 'alice', 'factor-research', 7, 'CNFutures',
             'workspace-a', 'live', '', 2);
        INSERT INTO research_graph_branches VALUES
            ('branch-v6', 'instance-v6', 'primary', 'capability_gap',
             'paused', '{}', '', '', '[]', 0, 'trace-v6', 1, 1),
            ('branch-v7', 'instance-v7', 'continuation-v7',
             'capability_gap', 'paused', '{}', '', '', '[]', 0,
             'trace-v7', 2, 2);
        INSERT INTO research_graph_trace VALUES
            ('trace-v6', 'instance-v6', 'branch-v6', 'edge-v6',
             'factor_semantics', 'capability_gap', '{}', '{}', 'alice', 1);
        """
    )
    evidence = json.dumps({
        "graph_continuation": {
            "schema_version": 1,
            "source_instance_id": "instance-v6",
            "source_branch_id": source_branch,
        },
    })
    conn.execute(
        """
        INSERT INTO research_graph_trace VALUES (
            'trace-v7', 'instance-v7', 'branch-v7',
            '__graph_continuation__', 'capability_gap', 'capability_gap',
            ?, '{}', 'alice', 2
        )
        """,
        (evidence,),
    )


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


def test_identity_upgrade_merges_continuations_without_losing_physical_rows(
    tmp_path,
) -> None:
    path = tmp_path / "identity-schema.sqlite"
    with connect_sqlite(path) as conn:
        _create_pre_identity_graph_schema(conn, source_branch="branch-v6")

        ensure_instance_branch_schema(conn)

        instances = conn.execute(
            """
            SELECT instance_id, work_package_id
            FROM research_graph_instances ORDER BY instance_id
            """
        ).fetchall()
        branches = conn.execute(
            """
            SELECT branch_id, hypothesis_branch_id, is_current_incarnation
            FROM research_graph_branches ORDER BY branch_id
            """
        ).fetchall()

    assert [dict(row) for row in instances] == [
        {"instance_id": "instance-v6", "work_package_id": "instance-v6"},
        {"instance_id": "instance-v7", "work_package_id": "instance-v6"},
    ]
    assert [dict(row) for row in branches] == [
        {
            "branch_id": "branch-v6",
            "hypothesis_branch_id": "branch-v6",
            "is_current_incarnation": 0,
        },
        {
            "branch_id": "branch-v7",
            "hypothesis_branch_id": "branch-v6",
            "is_current_incarnation": 1,
        },
    ]


def test_identity_upgrade_rejects_missing_continuation_source_atomically(
    tmp_path,
) -> None:
    path = tmp_path / "identity-schema-invalid.sqlite"
    with connect_sqlite(path) as conn:
        _create_pre_identity_graph_schema(conn, source_branch="missing")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="missing branch"):
            ensure_instance_branch_schema(conn)
        conn.rollback()
        instance_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(research_graph_instances)"
            ).fetchall()
        }
        branch_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(research_graph_branches)"
            ).fetchall()
        }

    assert "work_package_id" not in instance_columns
    assert "hypothesis_branch_id" not in branch_columns


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
            """
            SELECT run_id, trial_stage, trial_plan_schema_version,
                   trial_stage_id, evidence_action_id,
                   evidence_action_binding_json
            FROM research_runs
            """
        ).fetchone()

    assert "trial_stage" in columns
    assert {
        "trial_plan_schema_version",
        "trial_stage_id",
        "evidence_action_id",
        "evidence_action_binding_hash",
        "evidence_action_binding_json",
    }.issubset(columns)
    assert dict(row) == {
        "run_id": "run-1",
        "trial_stage": "",
        "trial_plan_schema_version": 0,
        "trial_stage_id": "",
        "evidence_action_id": "",
        "evidence_action_binding_json": "{}",
    }
