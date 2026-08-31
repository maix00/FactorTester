"""TrialPlan-v5 reuse of one information set across controlled stages."""

from __future__ import annotations

from copy import deepcopy

import pytest

from server.services import research_runs
from server.services.research_graph.trial_plan import (
    canonical_trial_plan,
    trial_plan_hash,
)
from server.services.research_graph.trial_plan.binding import (
    normalize_run_binding,
)
from server.services.research_graph.trial_plan.sample_identity import (
    derive_sample_identity,
)
from tests.server.test_trial_plan_contract_v5 import trial_plan_v5


STAGES = ("in-sample-ic", "gross-backtest", "net-backtest")
COHORT_PATHS = {
    "day": "Product/Futures/CNFutures/日夜盘/日盘/AP.CZC",
    "night": "Product/Futures/CNFutures/日夜盘/夜盘1/A.DCE",
}


def _run_spec(*, cohort: str, stage_id: str) -> dict:
    if stage_id == "in-sample-ic":
        analysis = "ic"
        module = {
            "settings": {
                "start_date": "2024-01-02",
                "end_date": "2024-12-31",
            },
            "paths": [COHORT_PATHS[cohort]],
        }
    else:
        analysis = "backtest"
        module = {
            "local_settings": {
                "start_date": "2024-01-02",
                "end_date": "2024-12-31",
                "fee_mode": (
                    "none" if stage_id == "gross-backtest" else "exchange"
                ),
            },
            "product_selections": {
                cohort: {"selected_paths": [COHORT_PATHS[cohort]]},
            },
        }
    return {
        "run_spec_version": 4,
        "workspace_id": f"workspace-{cohort}",
        "analyses": [analysis],
        "configuration": {"analyses": {analysis: module}},
    }


def _six_run_plan() -> tuple[dict, dict[str, dict]]:
    specs = {
        f"{cohort}:{stage_id}": _run_spec(
            cohort=cohort,
            stage_id=stage_id,
        )
        for stage_id in STAGES
        for cohort in COHORT_PATHS
    }
    run_hashes = {
        key: research_runs.hash_run_spec(spec)
        for key, spec in specs.items()
    }
    plan = trial_plan_v5()
    plan["stage_policy"] = {
        "ordered_stage_ids": list(STAGES),
        "entry_stage_id": STAGES[0],
        "entry_basis_ref": "decision-contract:new-research",
    }
    plan["samples"] = [
        {
            "sample_ref": f"sample:{cohort}:{stage_id}",
            "sample_hash": derive_sample_identity(
                specs[f"{cohort}:{stage_id}"]
            )["sample_hash"],
            "stage_id": stage_id,
            "semantic_role": (
                "selection"
                if stage_id == "in-sample-ic"
                else "validation"
            ),
            "run_spec_hashes": [run_hashes[f"{cohort}:{stage_id}"]],
        }
        for stage_id in STAGES
        for cohort in COHORT_PATHS
    ]
    plan["comparisons"] = [
        {
            "comparison_id": f"comparison:{stage_id}",
            "target_ref": "cohort:night",
            "baseline_ref": "cohort:day",
            "allowed_difference_refs": ["difference:session"],
            "members": [
                {
                    "run_spec_hash": run_hashes[f"{cohort}:{stage_id}"],
                    "trial_role": f"{cohort}:{stage_id}",
                }
                for cohort in COHORT_PATHS
            ],
        }
        for stage_id in STAGES
    ]
    plan["evidence_actions"] = [
        {
            "action_id": f"action:{stage_id}",
            "stage_id": stage_id,
            "obligation_refs": ["obligation:primary"],
            "capability_requirement_ref": "factor-validation.execute",
            "execution_mode": "job",
            "input_hash": f"{index + 5:x}" * 64,
            "expected_evidence_kind": "job-attempt",
            "evidence_contract_ref": "evidence-contract:job@1",
            "prerequisite_action_ids": (
                [] if index == 0 else [f"action:{STAGES[index - 1]}"]
            ),
            "cost_ref": "cost:medium",
            "stop_predicate_refs": ["stop:material-failure"],
            "run_spec_hashes": [
                run_hashes[f"{cohort}:{stage_id}"]
                for cohort in COHORT_PATHS
            ],
            "comparison_ids": [f"comparison:{stage_id}"],
        }
        for index, stage_id in enumerate(STAGES)
    ]
    return plan, specs


def test_same_day_and_night_cohorts_bind_across_three_stages() -> None:
    plan, specs = _six_run_plan()
    canonical = canonical_trial_plan(plan)
    plan_hash = trial_plan_hash(canonical)

    for cohort in COHORT_PATHS:
        sample_hashes = {
            derive_sample_identity(specs[f"{cohort}:{stage_id}"])[
                "sample_hash"
            ]
            for stage_id in STAGES
        }
        assert len(sample_hashes) == 1
    assert len({
        sample["sample_hash"] for sample in canonical["samples"]
    }) == 2

    for key, spec in specs.items():
        cohort, stage_id = key.split(":", 1)
        run_hash = research_runs.hash_run_spec(spec)
        binding = normalize_run_binding(
            trial_plan=canonical,
            expected_hash=plan_hash,
            expected_version=canonical["version"],
            run_spec_hash=run_hash,
            trial_role=key,
            comparison_id=f"comparison:{stage_id}",
            sample_identity=derive_sample_identity(spec),
            evidence_action_id=f"action:{stage_id}",
        )

        assert binding["sample_identity_assurance"] == "server_derived_bound"
        assert binding["action_stage_id"] == stage_id
        assert binding["sample_ref"] == f"sample:{cohort}:{stage_id}"


def test_same_sample_hash_cannot_be_duplicated_within_one_stage() -> None:
    plan, _ = _six_run_plan()
    plan["samples"][1]["sample_hash"] = plan["samples"][0]["sample_hash"]

    with pytest.raises(ValueError, match="at most once per stage"):
        canonical_trial_plan(plan)


def test_sample_ref_and_runspec_ownership_remain_unambiguous() -> None:
    plan, _ = _six_run_plan()
    duplicate_ref = deepcopy(plan)
    duplicate_ref["samples"][1]["sample_ref"] = (
        duplicate_ref["samples"][0]["sample_ref"]
    )
    with pytest.raises(ValueError, match="sample_ref values must be unique"):
        canonical_trial_plan(duplicate_ref)

    duplicate_run = deepcopy(plan)
    duplicate_run["samples"][1]["run_spec_hashes"] = (
        duplicate_run["samples"][0]["run_spec_hashes"]
    )
    with pytest.raises(ValueError, match="one RunSpec cannot cross"):
        canonical_trial_plan(duplicate_run)


def test_binding_rejects_a_different_universe_as_the_declared_sample() -> None:
    plan, specs = _six_run_plan()
    canonical = canonical_trial_plan(plan)
    day_spec = specs["day:in-sample-ic"]
    night_identity = derive_sample_identity(specs["night:in-sample-ic"])

    with pytest.raises(ValueError, match="server-derived sample identity"):
        normalize_run_binding(
            trial_plan=canonical,
            expected_hash=trial_plan_hash(canonical),
            expected_version=canonical["version"],
            run_spec_hash=research_runs.hash_run_spec(day_spec),
            trial_role="day:in-sample-ic",
            comparison_id="comparison:in-sample-ic",
            sample_identity=night_identity,
            evidence_action_id="action:in-sample-ic",
        )
