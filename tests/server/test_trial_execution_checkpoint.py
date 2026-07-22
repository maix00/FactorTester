"""Pure TrialPlan v5 execution checkpoint tests."""

from __future__ import annotations

import pytest

from server.services.research_graph.trial_plan import (
    advance_after_audit,
    agent_action_summary,
    initial_execution_checkpoint,
    transition_action_status,
    trial_plan_hash,
    validate_execution_checkpoint,
)
from tests.server.test_trial_plan_contract_v5 import trial_plan_v5


def _initial() -> tuple[dict, dict]:
    plan = trial_plan_v5()
    checkpoint = initial_execution_checkpoint(
        trial_plan=plan,
        expected_trial_plan_hash=trial_plan_hash(plan),
        execution_node="trial_execution",
    )
    return plan, checkpoint


def test_checkpoint_exposes_only_current_action_summary() -> None:
    _, checkpoint = _initial()

    assert agent_action_summary(checkpoint) == {
        "action_id": "action:ic",
        "status": "unreleased",
        "stage_id": "validation-1",
        "input_hash": "5" * 64,
        "qualification": None,
        "evidence_refs": [],
    }
    assert checkpoint["current_action_index"] == 0
    assert "action:backtest" not in str(agent_action_summary(checkpoint))


def test_action_must_be_admitted_and_audited_before_advance() -> None:
    plan, checkpoint = _initial()
    checkpoint = transition_action_status(checkpoint, target="released")
    checkpoint = transition_action_status(checkpoint, target="running")
    checkpoint = transition_action_status(
        checkpoint,
        target="evidence_ready",
        evidence_refs=["evidence:ic-result"],
    )
    with pytest.raises(ValueError, match="audited predecessor"):
        advance_after_audit(checkpoint, trial_plan=plan)
    checkpoint = transition_action_status(
        checkpoint,
        target="admitted",
        qualification="eligible",
    )
    checkpoint = transition_action_status(checkpoint, target="audited")

    next_checkpoint = advance_after_audit(checkpoint, trial_plan=plan)

    assert next_checkpoint["current_action_id"] == "action:backtest"
    assert next_checkpoint["current_action_status"] == "unreleased"
    assert next_checkpoint["current_action_output_evidence_refs"] == []
    assert next_checkpoint["completed_stage_mask"] == 1


def test_checkpoint_hash_and_transition_order_fail_closed() -> None:
    _, checkpoint = _initial()
    tampered = {**checkpoint, "current_action_id": "action:other"}
    with pytest.raises(ValueError, match="hash is invalid"):
        validate_execution_checkpoint(tampered)
    with pytest.raises(ValueError, match="invalid Evidence Action transition"):
        transition_action_status(checkpoint, target="running")
    released = transition_action_status(checkpoint, target="released")
    with pytest.raises(ValueError, match="requires Evidence references"):
        transition_action_status(released, target="evidence_ready")


def test_last_action_cannot_advance_past_plan() -> None:
    plan, checkpoint = _initial()
    for target, kwargs in (
        ("released", {}),
        ("evidence_ready", {"evidence_refs": ["evidence:ic"]}),
        ("admitted", {"qualification": "limited"}),
        ("audited", {}),
    ):
        checkpoint = transition_action_status(
            checkpoint,
            target=target,
            **kwargs,
        )
    checkpoint = advance_after_audit(checkpoint, trial_plan=plan)
    for target, kwargs in (
        ("released", {}),
        ("evidence_ready", {"evidence_refs": ["evidence:backtest"]}),
        ("admitted", {"qualification": "eligible"}),
        ("audited", {}),
    ):
        checkpoint = transition_action_status(
            checkpoint,
            target=target,
            **kwargs,
        )

    with pytest.raises(ValueError, match="no next Evidence Action"):
        advance_after_audit(checkpoint, trial_plan=plan)
