"""TrialPlan stage projection schema upgrade tests."""

from __future__ import annotations

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
