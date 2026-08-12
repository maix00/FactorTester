"""Persistence budgets for TrialPlan-v5 Evidence Actions."""

from __future__ import annotations

from copy import deepcopy

import orjson
import pytest

from server.services.research_graph.trial_plan import canonical_trial_plan
from tests.server.test_trial_plan_v5_shared_cohort import _six_run_plan


def _realistic_net_action_plan() -> tuple[dict, dict]:
    plan, _ = _six_run_plan()
    obligations = [
        "obligation:sgccs-incremental-value",
        "obligation:sgccs-cost-execution-survival",
        "obligation:sgccs-signal-schedule-strategy-policy",
        "obligation:sgcps-temporal-overlap-causal-gap",
    ]
    plan["secondary_obligation_refs"] = [
        *obligations,
        "obligation:secondary",
    ]
    action = plan["evidence_actions"][2]
    action["obligation_refs"] = obligations
    action["comparison_ids"] = [
        "comparison:net-backtest",
        "comparison:night-cost",
    ]
    action["cost_ref"] = "cost:mediumxx"
    extra_comparison = deepcopy(plan["comparisons"][2])
    extra_comparison["comparison_id"] = "comparison:night-cost"
    plan["comparisons"].append(extra_comparison)
    return plan, action


def test_realistic_858_byte_action_fits_persistence_budget() -> None:
    plan, action = _realistic_net_action_plan()

    assert len(orjson.dumps(action)) == 858
    canonical = canonical_trial_plan(plan)

    assert canonical["evidence_actions"][2]["action_id"] == (
        "action:net-backtest"
    )


def test_action_larger_than_1024_bytes_is_rejected() -> None:
    plan, action = _realistic_net_action_plan()
    obligations = [
        f"obligation:{index:02d}:" + ("x" * 48)
        for index in range(16)
    ]
    plan["secondary_obligation_refs"] = [
        *obligations,
        "obligation:secondary",
    ]
    action["obligation_refs"] = obligations

    assert len(orjson.dumps(action)) > 1024
    with pytest.raises(ValueError, match="exceeds 1024 bytes"):
        canonical_trial_plan(plan)


def test_whole_plan_remains_bounded_at_8192_bytes() -> None:
    plan, _ = _six_run_plan()
    plan["design_evidence_refs"] = [
        f"evidence:{index:02d}:" + ("x" * 230)
        for index in range(16)
    ]

    with pytest.raises(ValueError, match="TrialPlan exceeds 8192 bytes"):
        canonical_trial_plan(plan)
