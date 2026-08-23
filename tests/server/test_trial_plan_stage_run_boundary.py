"""ResearchRun enforcement for server-derived TrialPlan stages."""

from __future__ import annotations

import orjson
import pytest

import settings as Settings
from server.services import research_runs
from server.services.research_graph.trial_plan import (
    advance_trial_stage,
    canonical_trial_plan,
    project_trial_plan_stage,
    trial_plan_hash,
)
from server.services.research_graph.trial_plan.sample_identity import (
    derive_sample_identity,
)
from tests.server.trial_plan_fixtures import (
    initialize_branch,
    run_spec_with_dates,
    semantic_hash,
    trial_plan_v4,
)
from tools.data.sqlite.db import connect_sqlite


def _staged_specs_and_plan() -> tuple[list[dict], dict]:
    specs = [
        run_spec_with_dates(start, end, sample=stage)
        for stage, start, end in (
            ("selection", "2020-01-01", "2021-12-31"),
            ("validation", "2022-01-01", "2023-12-31"),
            ("confirmation", "2024-01-01", "2024-12-31"),
        )
    ]
    plan = trial_plan_v4()
    for sample, spec in zip(plan["sample_roles"], specs, strict=True):
        run_hash = semantic_hash(spec)
        sample["run_spec_hashes"] = [run_hash]
        sample["sample_hash"] = derive_sample_identity(spec)["sample_hash"]
    for member, spec in zip(
        plan["comparisons"][0]["members"],
        specs,
        strict=True,
    ):
        member["run_spec_hash"] = semantic_hash(spec)
    return specs, canonical_trial_plan(plan)


def _binding(plan: dict, index: int) -> dict:
    member = plan["comparisons"][0]["members"][index]
    return {
        "instance_id": "instance-1",
        "branch_id": "branch-1",
        "trial_plan": plan,
        "trial_plan_hash": trial_plan_hash(plan),
        "trial_plan_version": plan["version"],
        "trial_role": member["trial_role"],
        "comparison_id": "main-comparison",
    }


def test_run_uses_current_server_derived_stage_and_rejects_future_stage(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "stage-run.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    specs, plan = _staged_specs_and_plan()
    plan_hash = trial_plan_hash(plan)
    projection = project_trial_plan_stage(
        trial_plan=plan,
        trial_plan_hash=plan_hash,
        current_trial_plan_hash="",
        current_projection={},
        execution_node="cheap_factor_diagnostics",
    )
    projection = advance_trial_stage(projection)
    initialize_branch(path, plan_hash)
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node='cheap_factor_diagnostics',
                trial_stage_projection_json=?
            WHERE branch_id='branch-1'
            """,
            (orjson.dumps(projection).decode(),),
        )

    with pytest.raises(ValueError, match="current TrialPlan stage"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="confirmation-too-early",
            configuration_revision=1,
            run_spec=specs[2],
            trial_binding=_binding(plan, 2),
        )
    with pytest.raises(ValueError, match="current TrialPlan stage"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="selection-already-complete",
            configuration_revision=1,
            run_spec=specs[0],
            trial_binding=_binding(plan, 0),
        )

    statements: list[str] = []

    def traced_connect(*args, **kwargs):
        conn = connect_sqlite(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(research_runs, "connect_sqlite", traced_connect)
    created = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="validation-now",
        configuration_revision=1,
        run_spec=specs[1],
        trial_binding=_binding(plan, 1),
    )
    create_statements = list(statements)
    statements.clear()
    loaded = research_runs.load_run(
        run_id=created["run_id"],
        owner="alice",
    )

    assert created["trial_role"] == "candidate"
    assert created["trial_stage"] == "validation"
    assert loaded is not None
    assert loaded["trial_stage"] == "validation"
    normalized = [
        " ".join(item.upper().split())
        for item in create_statements
    ]
    assert sum(item.startswith("SELECT") for item in normalized) == 1
    assert sum(
        item.startswith("INSERT INTO RESEARCH_RUNS")
        for item in normalized
    ) == 1
    assert all("RESEARCH_GRAPH_TRACE" not in item for item in normalized)


def test_run_requires_the_plan_bound_execution_node(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "stage-node.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    specs, plan = _staged_specs_and_plan()
    plan_hash = trial_plan_hash(plan)
    projection = project_trial_plan_stage(
        trial_plan=plan,
        trial_plan_hash=plan_hash,
        current_trial_plan_hash="",
        current_projection={},
        execution_node="cheap_factor_diagnostics",
    )
    initialize_branch(path, plan_hash)

    with pytest.raises(ValueError, match="stage projection"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="legacy-unbound",
            configuration_revision=1,
            run_spec=specs[0],
            trial_binding=_binding(plan, 0),
        )

    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE research_graph_branches
            SET trial_stage_projection_json=?
            WHERE branch_id='branch-1'
            """,
            (orjson.dumps(projection).decode(),),
        )

    with pytest.raises(ValueError, match="execution node"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="wrong-node",
            configuration_revision=1,
            run_spec=specs[0],
            trial_binding=_binding(plan, 0),
        )
