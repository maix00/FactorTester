"""Protected sample exposure is keyed by stage, not comparison arm."""

from __future__ import annotations

import orjson
import pytest

import settings as Settings
from server.services import research_runs
from server.services.research_graph.trial_plan import (
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


def _single_stage_plan(
    spec: dict,
    *,
    stage: str,
    plan_id: str,
) -> dict:
    index = {
        "selection": 0,
        "validation": 1,
        "confirmation": 2,
    }[stage]
    plan = trial_plan_v4()
    sample = plan["sample_roles"][index]
    member = plan["comparisons"][0]["members"][index]
    run_hash = semantic_hash(spec)
    sample["run_spec_hashes"] = [run_hash]
    sample["sample_hash"] = derive_sample_identity(spec)["sample_hash"]
    member["run_spec_hash"] = run_hash
    plan["sample_roles"] = [sample]
    plan["comparisons"][0]["members"] = [member]
    plan["trial_plan_id"] = plan_id
    plan["hypothesis_ref"] = f"hypothesis:{plan_id}"
    plan["stage_policy"] = {
        "ordered_stages": [stage],
        "entry_stage": stage,
        "entry_basis_ref": f"decision-contract:{plan_id}",
    }
    return canonical_trial_plan(plan)


def _binding(plan: dict) -> dict:
    member = plan["comparisons"][0]["members"][0]
    return {
        "instance_id": "instance-1",
        "branch_id": "branch-1",
        "trial_plan": plan,
        "trial_plan_hash": trial_plan_hash(plan),
        "trial_plan_version": plan["version"],
        "trial_role": member["trial_role"],
        "comparison_id": "main-comparison",
    }


def _bind_plan(path, plan: dict) -> None:
    plan_hash = trial_plan_hash(plan)
    projection = project_trial_plan_stage(
        trial_plan=plan,
        trial_plan_hash=plan_hash,
        current_trial_plan_hash="",
        current_projection={},
        execution_node="cheap_factor_diagnostics",
    )
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_trial_plan_hash=?,
                current_node='cheap_factor_diagnostics',
                trial_stage_projection_json=?
            WHERE branch_id='branch-1'
            """,
            (plan_hash, orjson.dumps(projection).decode()),
        )


def test_protected_stage_cannot_hide_reuse_behind_same_comparison_role(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "candidate-reuse.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    selection_spec = run_spec_with_dates("2024-01-01", "2024-12-31")
    selection = _single_stage_plan(
        selection_spec,
        stage="selection",
        plan_id="selection-plan",
    )
    initialize_branch(path, trial_plan_hash(selection))
    _bind_plan(path, selection)
    research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="selection",
        configuration_revision=1,
        run_spec=selection_spec,
        trial_binding=_binding(selection),
    )

    confirmation_spec = {
        **selection_spec,
        "factor_revision": 2,
    }
    confirmation = _single_stage_plan(
        confirmation_spec,
        stage="confirmation",
        plan_id="confirmation-plan",
    )
    _bind_plan(path, confirmation)

    with pytest.raises(ValueError, match="already exposed"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="confirmation",
            configuration_revision=1,
            run_spec=confirmation_spec,
            trial_binding=_binding(confirmation),
        )
