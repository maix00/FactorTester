"""TrialPlan stage policy and projection contract tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from server.services.research_graph.trial_plan import (
    advance_trial_stage,
    canonical_trial_plan,
    normalize_run_binding,
    project_trial_plan_stage,
    trial_plan_hash,
    trial_stage_guard_facts,
)
from tests.server.trial_plan_fixtures import trial_plan_v4


def test_v4_stage_policy_separates_stage_from_comparison_arm() -> None:
    plan = canonical_trial_plan(trial_plan_v4())

    assert plan["stage_policy"]["entry_stage"] == "selection"
    assert {
        member["trial_role"]
        for member in plan["comparisons"][0]["members"]
    } == {"candidate"}
    assert plan["parent_trial_plan_hash"] is None

    invalid = deepcopy(trial_plan_v4())
    invalid["stage_policy"]["ordered_stages"] = [
        "validation",
        "selection",
    ]
    with pytest.raises(ValueError, match="canonical stage order"):
        canonical_trial_plan(invalid)


def test_v4_run_binding_derives_stage_from_sample_not_comparison_arm() -> None:
    plan = canonical_trial_plan(trial_plan_v4())
    binding = normalize_run_binding(
        trial_plan=plan,
        expected_hash=trial_plan_hash(plan),
        expected_version=1,
        run_spec_hash="b" * 64,
        trial_role="candidate",
        comparison_id="main-comparison",
        sample_identity={"sample_hash": "e" * 64},
    )

    assert binding["trial_role"] == "candidate"
    assert binding["trial_stage"] == "validation"


def test_stage_projection_enforces_lineage_and_frozen_trial_design() -> None:
    first = canonical_trial_plan(trial_plan_v4())
    first_hash = trial_plan_hash(first)
    projection = project_trial_plan_stage(
        trial_plan=first,
        trial_plan_hash=first_hash,
        current_trial_plan_hash="",
        current_projection={},
    )

    assert projection["current_stage"] == "selection"
    assert projection["plan_version"] == 1
    assert projection["completed_mask"] == 0

    advanced = advance_trial_stage(projection)
    assert advanced["current_stage"] == "validation"
    assert advanced["completed_mask"] == 1

    changed_run = deepcopy(first)
    changed_run["version"] = 2
    changed_run["parent_trial_plan_hash"] = first_hash
    changed_run["sample_roles"][1]["run_spec_hashes"] = ["9" * 64]
    changed_run["comparisons"][0]["members"][1]["run_spec_hash"] = "9" * 64
    with pytest.raises(ValueError, match="frozen trial design"):
        project_trial_plan_stage(
            trial_plan=changed_run,
            trial_plan_hash=trial_plan_hash(changed_run),
            current_trial_plan_hash=first_hash,
            current_projection=advanced,
        )

    child = deepcopy(first)
    child["version"] = 2
    child["parent_trial_plan_hash"] = first_hash
    child_projection = project_trial_plan_stage(
        trial_plan=child,
        trial_plan_hash=trial_plan_hash(child),
        current_trial_plan_hash=first_hash,
        current_projection=advanced,
    )
    assert child_projection["plan_version"] == 2
    assert child_projection["current_stage"] == "validation"

    changed_partition = deepcopy(child)
    changed_partition["sample_roles"][1]["sample_hash"] = "8" * 64
    with pytest.raises(ValueError, match="partition commitment"):
        project_trial_plan_stage(
            trial_plan=changed_partition,
            trial_plan_hash=trial_plan_hash(changed_partition),
            current_trial_plan_hash=first_hash,
            current_projection=advanced,
        )


def test_direct_confirmation_is_terminal_and_not_revision_eligible() -> None:
    plan = trial_plan_v4()
    plan["sample_roles"] = [plan["sample_roles"][2]]
    plan["comparisons"][0]["members"] = [
        plan["comparisons"][0]["members"][2]
    ]
    plan["stage_policy"] = {
        "ordered_stages": ["confirmation"],
        "entry_stage": "confirmation",
        "entry_basis_ref": "decision-contract:pinned-existing-family",
    }
    canonical = canonical_trial_plan(plan)
    projection = project_trial_plan_stage(
        trial_plan=canonical,
        trial_plan_hash=trial_plan_hash(canonical),
        current_trial_plan_hash="",
        current_projection={},
    )

    assert trial_stage_guard_facts(
        projection=projection,
        adjudication_action="research_decision",
    ) == {
        "current_trial_stage_executable": True,
        "current_trial_stage_allows_revision": False,
        "next_trial_stage_required": False,
        "trial_stage_advance_authorized": False,
    }
    with pytest.raises(ValueError, match="no next TrialPlan stage"):
        trial_stage_guard_facts(
            projection=projection,
            adjudication_action="advance_trial_stage",
        )
