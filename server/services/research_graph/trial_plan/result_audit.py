"""Bind one semantic adjudication to an admitted Evidence Action."""

from __future__ import annotations

from typing import Any

from ..research_cycle.adjudication import validate_adjudication_pair
from .execution_checkpoint_contract import (
    seal_checkpoint,
    validate_checkpoint_plan_identity,
    validate_execution_checkpoint,
    without_checkpoint_hash,
)


def audit_current_action(
    checkpoint: dict[str, Any],
    *,
    trial_plan: dict[str, Any],
    proposal: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Record an authority-bound audit; do not choose the next Graph edge."""
    current = validate_execution_checkpoint(checkpoint)
    plan = validate_checkpoint_plan_identity(current, trial_plan)
    if current["current_action_status"] != "admitted":
        raise ValueError("result audit requires admitted Evidence")
    validated_proposal, validated_decision = validate_adjudication_pair(
        proposal,
        decision,
        expected_contract_hash=plan["decision_contract_hash"],
        expected_trial_plan_hash=_trial_plan_hash(plan),
        expected_methodology_hash=plan["methodology_hash"],
    )
    if set(validated_proposal["evidence_refs"]) != set(
        current["current_action_output_evidence_refs"]
    ):
        raise ValueError("result audit does not cover current Action Evidence")
    value = without_checkpoint_hash(current)
    value.update({
        "current_action_status": "audited",
        "current_action_audit_ref": (
            "adjudication:" + validated_decision["decision_id"]
        ),
        "current_action_audit_disposition": validated_decision["disposition"],
        "current_action_audit_route": validated_proposal["recommended_action"],
    })
    return seal_checkpoint(value)


def _trial_plan_hash(plan: dict[str, Any]) -> str:
    from .contract import trial_plan_hash

    return trial_plan_hash(plan)
