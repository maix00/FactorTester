"""TrialPlan v5 Evidence Action contract tests."""

from __future__ import annotations

import orjson
import pytest

from server.services.research_graph.trial_plan import (
    canonical_trial_plan,
    trial_plan_hash,
)


def _action(
    action_id: str,
    stage_id: str,
    input_hash: str,
    *,
    prerequisites: list[str] | None = None,
    run_spec_hashes: list[str] | None = None,
) -> dict:
    return {
        "action_id": action_id,
        "stage_id": stage_id,
        "obligation_refs": ["obligation:primary"],
        "capability_requirement_ref": "factor-validation.ic",
        "execution_mode": "job",
        "input_hash": input_hash,
        "expected_evidence_kind": "cross-sectional-ic",
        "evidence_contract_ref": "evidence-contract:ic@1",
        "prerequisite_action_ids": prerequisites or [],
        "cost_ref": "cost:medium",
        "stop_predicate_refs": ["stop:material-failure"],
        "run_spec_hashes": run_spec_hashes or ["a" * 64],
        "comparison_ids": ["comparison:parent-child"],
    }


def trial_plan_v5() -> dict:
    return {
        "schema_version": 5,
        "trial_plan_id": "plan-v5",
        "version": 1,
        "hypothesis_ref": "hypothesis:sgcps",
        "trial_family": "family:sgcps",
        "protocol_ref": "protocol:factor-validation@1",
        "outcomes": {
            "primary": ["rank-ic"],
            "secondary": ["coverage"],
        },
        "samples": [
            {
                "sample_ref": "sample:validation-1",
                "sample_hash": "1" * 64,
                "stage_id": "validation-1",
                "semantic_role": "validation",
                "run_spec_hashes": ["a" * 64],
            },
            {
                "sample_ref": "sample:validation-2",
                "sample_hash": "2" * 64,
                "stage_id": "validation-2",
                "semantic_role": "validation",
                "run_spec_hashes": ["b" * 64],
            },
        ],
        "comparisons": [{
            "comparison_id": "comparison:parent-child",
            "target_ref": "factor:sgcps-child",
            "baseline_ref": "factor:sgcps-parent",
            "allowed_difference_refs": ["difference:price-input"],
            "members": [
                {"run_spec_hash": "a" * 64, "trial_role": "baseline"},
                {"run_spec_hash": "b" * 64, "trial_role": "target"},
            ],
        }],
        "stopping": {
            "rule_ref": "stop-rule:fixed-information",
            "monitored_outcomes": ["rank-ic"],
            "parameters": {"minimum_observations": 250},
        },
        "multiplicity": {
            "method_ref": "method:ledger-bound",
            "family_ref": "trial-family:sgcps",
            "dependence_assumptions": ["dependence:time-series"],
        },
        "criteria": {
            "rejection_ref": "criterion:reject",
            "revision_ref": "criterion:revise",
            "continuation_ref": "criterion:continue",
        },
        "decision_contract_hash": "3" * 64,
        "methodology_hash": "4" * 64,
        "parent_trial_plan_hash": None,
        "stage_policy": {
            "ordered_stage_ids": ["validation-1", "validation-2"],
            "entry_stage_id": "validation-1",
            "entry_basis_ref": "decision-contract:new-research",
        },
        "primary_obligation_ref": "obligation:primary",
        "secondary_obligation_refs": ["obligation:secondary"],
        "design_evidence_refs": ["evidence:partition-manifest"],
        "trial_ledger_ref": "ledger:trial-selection",
        "holdout_access_ledger_ref": "ledger:holdout-access",
        "reopen_predicate_refs": ["reopen:new-data"],
        "evidence_actions": [
            _action("action:ic", "validation-1", "5" * 64),
            _action(
                "action:backtest",
                "validation-2",
                "6" * 64,
                prerequisites=["action:ic"],
                run_spec_hashes=["b" * 64],
            ),
        ],
    }


def test_v5_separates_stage_identity_from_semantic_role() -> None:
    canonical = canonical_trial_plan(trial_plan_v5())

    assert canonical["stage_policy"]["ordered_stage_ids"] == [
        "validation-1",
        "validation-2",
    ]
    assert [item["semantic_role"] for item in canonical["samples"]] == [
        "validation",
        "validation",
    ]
    assert canonical["primary_obligation_ref"] == "obligation:primary"
    assert canonical["evidence_actions"][1]["prerequisite_action_ids"] == [
        "action:ic"
    ]
    assert trial_plan_hash(canonical) == trial_plan_hash(trial_plan_v5())
    assert len(orjson.dumps(canonical)) <= 8192


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda plan: plan["evidence_actions"][0].update({
                "obligation_refs": ["obligation:unknown"]
            }),
            "not declared by TrialPlan",
        ),
        (
            lambda plan: plan["evidence_actions"][0].update({
                "stage_id": "future-stage"
            }),
            "not declared by stage_policy",
        ),
        (
            lambda plan: plan["evidence_actions"][0].update({
                "prerequisite_action_ids": ["action:backtest"]
            }),
            "must reference earlier actions",
        ),
        (
            lambda plan: plan.update({
                "secondary_obligation_refs": ["obligation:primary"]
            }),
            "cannot also be secondary",
        ),
    ],
)
def test_v5_rejects_ambiguous_action_design(mutation, message: str) -> None:
    plan = trial_plan_v5()
    mutation(plan)

    with pytest.raises(ValueError, match=message):
        canonical_trial_plan(plan)


def test_v5_bounds_action_count_and_rejects_v4_field_aliases() -> None:
    plan = trial_plan_v5()
    plan["evidence_actions"] = [
        _action(f"action:{index}", "validation-1", f"{index + 1:x}" * 64)
        for index in range(9)
    ]
    with pytest.raises(ValueError, match="at most 8"):
        canonical_trial_plan(plan)

    plan = trial_plan_v5()
    plan["sample_roles"] = plan["samples"]
    with pytest.raises(ValueError, match="unsupported fields: sample_roles"):
        canonical_trial_plan(plan)


def test_eight_action_plan_has_its_own_persistence_budget() -> None:
    plan = trial_plan_v5()
    plan["evidence_actions"] = [
        _action(
            f"action:{index}",
            "validation-1",
            f"{index + 1:x}" * 64,
            prerequisites=([f"action:{index - 1}"] if index else []),
            run_spec_hashes=["a" * 64],
        )
        for index in range(8)
    ]

    encoded = orjson.dumps(canonical_trial_plan(plan))

    assert 4096 < len(encoded) <= 8192


def test_job_action_is_explicitly_scoped_to_stage_and_comparison() -> None:
    plan = trial_plan_v5()
    plan["evidence_actions"][0]["run_spec_hashes"] = ["b" * 64]
    with pytest.raises(ValueError, match="belong to the Action stage"):
        canonical_trial_plan(plan)

    plan = trial_plan_v5()
    plan["evidence_actions"][0]["comparison_ids"] = ["comparison:missing"]
    with pytest.raises(ValueError, match="not declared by TrialPlan"):
        canonical_trial_plan(plan)


def test_non_job_action_cannot_claim_research_runs() -> None:
    plan = trial_plan_v5()
    plan["evidence_actions"][0].update({
        "execution_mode": "sync_cli",
        "run_spec_hashes": [],
        "comparison_ids": [],
    })
    canonical = canonical_trial_plan(plan)
    assert canonical["evidence_actions"][0]["run_spec_hashes"] == []

    plan["evidence_actions"][0]["run_spec_hashes"] = ["a" * 64]
    with pytest.raises(ValueError, match="only for job execution"):
        canonical_trial_plan(plan)
