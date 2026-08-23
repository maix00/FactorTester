"""ResearchRun binding to one released TrialPlan v5 Evidence Action."""

from __future__ import annotations

from copy import deepcopy

import orjson
import pytest

import settings as Settings
from server.jobs.repository import JobRepository
from server.services import research_runs
from server.services.research_graph.trial_plan import (
    initial_execution_checkpoint,
    transition_action_status,
    trial_plan_hash,
)
from server.services.research_graph.trial_plan.sample_identity import (
    derive_sample_identity,
)
from server.services.research_graph.work_packages import insert_active
from tests.server.test_trial_plan_contract_v5 import trial_plan_v5
from tests.server.trial_plan_fixtures import (
    initialize_branch,
    job_record,
    run_spec_with_dates,
    semantic_hash,
)
from tools.data.sqlite.db import connect_sqlite


def _released_trial(path) -> tuple[dict, dict, dict]:
    baseline = run_spec_with_dates(
        "2020-01-01", "2023-12-31", variant="baseline",
    )
    target = run_spec_with_dates(
        "2020-01-01", "2023-12-31", variant="target",
    )
    baseline_hash = semantic_hash(baseline)
    target_hash = semantic_hash(target)
    sample_hash = derive_sample_identity(baseline)["sample_hash"]
    plan = trial_plan_v5()
    plan["samples"][0].update({
        "sample_hash": sample_hash,
        "run_spec_hashes": [baseline_hash, target_hash],
    })
    plan["comparisons"][0]["members"] = [
        {"run_spec_hash": baseline_hash, "trial_role": "baseline"},
        {"run_spec_hash": target_hash, "trial_role": "target"},
        plan["comparisons"][0]["members"][1],
    ]
    plan["evidence_actions"][0]["run_spec_hashes"] = [
        baseline_hash,
        target_hash,
    ]
    plan_hash = trial_plan_hash(plan)
    checkpoint = initial_execution_checkpoint(
        trial_plan=plan,
        expected_trial_plan_hash=plan_hash,
        execution_node="trial_execution",
    )
    checkpoint = transition_action_status(checkpoint, target="released")
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
            SET current_node='trial_execution', latest_trace_id='trace-release',
                trial_stage_projection_json=?
            WHERE branch_id='branch-1'
            """,
            (orjson.dumps(checkpoint).decode(),),
        )
    return plan, checkpoint, {"baseline": baseline, "target": target}


def _binding(plan: dict, checkpoint: dict, *, role: str) -> dict:
    return {
        "instance_id": "instance-1",
        "branch_id": "branch-1",
        "trial_plan": plan,
        "trial_plan_hash": trial_plan_hash(plan),
        "trial_plan_version": plan["version"],
        "trial_role": role,
        "comparison_id": "comparison:parent-child",
        "evidence_action_id": "action:ic",
        "expected_checkpoint_hash": checkpoint["projection_hash"],
        "expected_latest_trace_id": "trace-release",
    }


def test_released_action_binds_all_declared_runs_without_advancing_cursor(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "action-run.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    plan, checkpoint, specs = _released_trial(path)

    created = [
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id=f"configuration-{role}",
            configuration_revision=1,
            run_spec=specs[role],
            trial_binding=_binding(plan, checkpoint, role=role),
        )
        for role in ("baseline", "target")
    ]

    assert {item["evidence_action_id"] for item in created} == {"action:ic"}
    assert {item["trial_stage_id"] for item in created} == {"validation-1"}
    assert {item["graph_execution_node"] for item in created} == {
        "trial_execution"
    }
    assert all(item["evidence_action_binding"] for item in created)
    job = JobRepository(path).create(
        job_record(created[0]["run_id"], specs["baseline"])
    )
    projected = research_runs.load_job_evidence_projection(
        job_id=job.job_id,
        owner="alice",
    )
    assert projected is not None
    assert projected["trial_binding"]["evidence_action_id"] == "action:ic"
    assert projected["trial_binding"]["evidence_action_binding"][
        "release_checkpoint_hash"
    ] == checkpoint["projection_hash"]
    with connect_sqlite(path) as conn:
        stored = orjson.loads(conn.execute(
            "SELECT trial_stage_projection_json FROM research_graph_branches "
            "WHERE branch_id='branch-1'"
        ).fetchone()["trial_stage_projection_json"])
    assert stored["current_action_status"] == "released"


def test_action_run_binding_fails_closed_on_stale_checkpoint_and_duplicate(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "action-run-fail.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    plan, checkpoint, specs = _released_trial(path)
    stale = _binding(plan, checkpoint, role="baseline")
    stale["expected_checkpoint_hash"] = "f" * 64
    with pytest.raises(ValueError, match="checkpoint changed"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="configuration-stale",
            configuration_revision=1,
            run_spec=specs["baseline"],
            trial_binding=stale,
        )

    binding = _binding(plan, checkpoint, role="baseline")
    research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-first",
        configuration_revision=1,
        run_spec=specs["baseline"],
        trial_binding=binding,
    )
    with pytest.raises(ValueError, match="already has this ResearchRun"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="configuration-duplicate",
            configuration_revision=1,
            run_spec=specs["baseline"],
            trial_binding=deepcopy(binding),
        )
