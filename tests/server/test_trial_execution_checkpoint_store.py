"""Atomic persistence tests for the TrialPlan v5 execution checkpoint."""

from __future__ import annotations

import orjson
import pytest

from server.services.research_graph.trial_plan import (
    ExecutionCheckpointConflictError,
    apply_execution_checkpoint_operation,
    initial_execution_checkpoint,
    transition_action_status,
    trial_plan_hash,
)
from server.services.research_graph.work_packages import insert_active
from tests.server.test_trial_plan_contract_v5 import trial_plan_v5
from tests.server.trial_plan_fixtures import initialize_branch
from tools.data.sqlite.db import connect_sqlite


def _branch(path) -> tuple[dict, dict]:
    plan = trial_plan_v5()
    plan_hash = trial_plan_hash(plan)
    checkpoint = initial_execution_checkpoint(
        trial_plan=plan,
        expected_trial_plan_hash=plan_hash,
        execution_node="trial_execution",
    )
    initialize_branch(path, plan_hash)
    with connect_sqlite(path) as conn:
        insert_active(
            conn,
            owner="alice",
            work_package_id="instance-1",
            workspace_id="workspace-1",
            created_at=1,
        )
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node='trial_execution', latest_trace_id='trace-1',
                trial_stage_projection_json=?
            WHERE branch_id='branch-1'
            """,
            (orjson.dumps(checkpoint).decode(),),
        )
    return plan, checkpoint


def test_checkpoint_compare_and_swap_persists_one_legal_step(tmp_path) -> None:
    path = tmp_path / "checkpoint.sqlite"
    plan, checkpoint = _branch(path)
    released = transition_action_status(checkpoint, target="released")

    with connect_sqlite(path) as conn:
        statements: list[str] = []
        conn.set_trace_callback(statements.append)
        stored = apply_execution_checkpoint_operation(
            conn,
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            trial_plan=plan,
            expected_latest_trace_id="trace-1",
            expected_checkpoint_hash=checkpoint["projection_hash"],
            operation="release",
        )
        conn.set_trace_callback(None)

    assert stored["checkpoint"] == released
    hot_path = [
        statement for statement in statements
        if statement.lstrip().upper().startswith(("SELECT", "UPDATE"))
    ]
    assert len(hot_path) == 2
    with connect_sqlite(path) as conn:
        row = conn.execute(
            "SELECT trial_stage_projection_json, latest_trace_id "
            "FROM research_graph_branches WHERE branch_id='branch-1'"
        ).fetchone()
    assert orjson.loads(row["trial_stage_projection_json"]) == released
    assert row["latest_trace_id"] == "trace-1"


def test_checkpoint_compare_and_swap_rejects_stale_or_skipped_state(tmp_path) -> None:
    path = tmp_path / "checkpoint-stale.sqlite"
    plan, checkpoint = _branch(path)
    released = transition_action_status(checkpoint, target="released")

    with connect_sqlite(path) as conn:
        with pytest.raises(ExecutionCheckpointConflictError, match="trace"):
            apply_execution_checkpoint_operation(
                conn,
                instance_id="instance-1",
                branch_id="branch-1",
                owner="alice",
                trial_plan=plan,
                expected_latest_trace_id="trace-stale",
                expected_checkpoint_hash=checkpoint["projection_hash"],
                operation="release",
            )
        with pytest.raises(ValueError, match="unreleased -> running"):
            apply_execution_checkpoint_operation(
                conn,
                instance_id="instance-1",
                branch_id="branch-1",
                owner="alice",
                trial_plan=plan,
                expected_latest_trace_id="trace-1",
                expected_checkpoint_hash=checkpoint["projection_hash"],
                operation="mark_running",
            )
