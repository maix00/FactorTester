"""Database binding for a preregistered cohort reused across v5 stages."""

from __future__ import annotations

import orjson

import settings as Settings
from server.services import research_runs
from server.services.research_graph.trial_plan import (
    initial_execution_checkpoint,
    trial_plan_hash,
)
from server.services.research_graph.trial_plan.execution_checkpoint_contract import (
    seal_checkpoint,
    without_checkpoint_hash,
)
from server.services.research_graph.trial_plan.sample_identity import (
    derive_sample_identity,
)
from server.services.research_graph.work_packages import insert_active
from tests.server.test_trial_plan_v5_shared_cohort import _six_run_plan
from tests.server.trial_plan_fixtures import initialize_branch
from tools.data.sqlite.db import connect_sqlite


def _released_checkpoint(plan: dict, *, action_index: int) -> dict:
    checkpoint = initial_execution_checkpoint(
        trial_plan=plan,
        expected_trial_plan_hash=trial_plan_hash(plan),
        execution_node="trial_execution",
    )
    action = plan["evidence_actions"][action_index]
    value = without_checkpoint_hash(checkpoint)
    value.update({
        "current_stage_id": action["stage_id"],
        "completed_stage_mask": (1 << action_index) - 1,
        "current_action_index": action_index,
        "current_action_id": action["action_id"],
        "current_action_status": "released",
        "current_action_input_hash": action["input_hash"],
        "current_action_output_evidence_refs": [],
        "current_action_qualification": None,
        "current_action_audit_ref": None,
        "current_action_audit_disposition": None,
        "current_action_audit_route": None,
    })
    return seal_checkpoint(value)


def _binding(
    plan: dict,
    checkpoint: dict,
    *,
    stage_id: str,
    trial_role: str,
) -> dict:
    return {
        "instance_id": "instance-1",
        "branch_id": "branch-1",
        "trial_plan": plan,
        "trial_plan_hash": trial_plan_hash(plan),
        "trial_plan_version": plan["version"],
        "trial_role": trial_role,
        "comparison_id": f"comparison:{stage_id}",
        "evidence_action_id": f"action:{stage_id}",
        "expected_checkpoint_hash": checkpoint["projection_hash"],
        "expected_latest_trace_id": "trace-release",
    }


def test_same_frozen_sample_can_run_in_later_declared_v5_stage(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "shared-cohort.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    plan, specs = _six_run_plan()
    plan_hash = trial_plan_hash(plan)
    initialize_branch(path, plan_hash)
    with connect_sqlite(path) as conn:
        insert_active(
            conn,
            owner="alice",
            work_package_id="instance-1",
            workspace_id="workspace-1",
            created_at=1,
        )

    ic_checkpoint = _released_checkpoint(plan, action_index=0)
    _store_checkpoint(path, ic_checkpoint)
    ic_spec = specs["day:in-sample-ic"]
    research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-day-ic",
        configuration_revision=1,
        run_spec=ic_spec,
        trial_binding=_binding(
            plan,
            ic_checkpoint,
            stage_id="in-sample-ic",
            trial_role="day:in-sample-ic",
        ),
    )

    gross_checkpoint = _released_checkpoint(plan, action_index=1)
    _store_checkpoint(path, gross_checkpoint)
    gross_spec = specs["day:gross-backtest"]
    gross = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-day-gross",
        configuration_revision=1,
        run_spec=gross_spec,
        trial_binding=_binding(
            plan,
            gross_checkpoint,
            stage_id="gross-backtest",
            trial_role="day:gross-backtest",
        ),
    )

    assert gross["trial_stage"] == "validation"
    assert gross["sample_identity_hash"] == (
        derive_sample_identity(ic_spec)["sample_hash"]
    )


def _store_checkpoint(path, checkpoint: dict) -> None:
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node='trial_execution',
                latest_trace_id='trace-release',
                trial_stage_projection_json=?
            WHERE branch_id='branch-1'
            """,
            (orjson.dumps(checkpoint).decode(),),
        )
