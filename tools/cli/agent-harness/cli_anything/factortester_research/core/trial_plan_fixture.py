"""Declarative activation-fixture checks without server dependencies."""

from __future__ import annotations

from typing import Any

from .trial_plan_fixture_controls import validate_control_pairs
from .trial_plan_fixture_dag import (
    actions_by_id,
    role_map,
    validate_capabilities,
    validate_dependencies,
)


def validate_trial_plan_fixture(
    trial_plan: Any,
    *,
    validation_contract: Any,
    action_input_summaries: Any,
    run_spec_summaries: Any,
) -> dict[str, Any]:
    """Validate declared roles, dependency DAG, inputs, and controls."""
    if not isinstance(trial_plan, dict):
        raise ValueError("trial_plan must be an object")
    if not isinstance(validation_contract, dict):
        raise ValueError("validation_contract must be an object")
    actions = trial_plan.get("evidence_actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("trial_plan.evidence_actions must be non-empty")
    by_id = actions_by_id(actions)
    roles = role_map(validation_contract.get("action_roles"), by_id)
    validate_capabilities(
        validation_contract.get("capability_by_role"),
        roles,
        by_id,
    )
    dependencies = validate_dependencies(
        validation_contract.get("required_dependency_roles"),
        roles,
        by_id,
    )
    _validate_action_inputs(
        validation_contract,
        roles,
        action_input_summaries,
    )
    _validate_run_cohorts(
        validation_contract.get("run_cohorts_by_role"),
        roles,
        by_id,
        run_spec_summaries,
    )
    control_pairs = validate_control_pairs(
        validation_contract.get("control_pairs"),
        run_spec_summaries,
    )
    return {
        "passed": True,
        "ordered_action_ids": [
            str(item["action_id"]) for item in actions
        ],
        "declared_action_roles": sorted(roles),
        "required_dependencies": dependencies,
        "control_pairs": control_pairs,
    }
def _validate_action_inputs(
    contract: dict[str, Any],
    roles: dict[str, str],
    summaries: Any,
) -> None:
    if not isinstance(summaries, dict):
        raise ValueError("action_input_summaries must be an object")
    product = contract.get("product_eligibility") or {}
    product_input = summaries.get(roles.get(product.get("role"))) or {}
    if product_input.get("candidate_scope") != product.get("candidate_scope"):
        raise ValueError("product eligibility candidate scope does not match")
    if set(product_input.get("eligibility_criteria") or []) != set(
        product.get("required_criteria") or []
    ):
        raise ValueError("product eligibility criteria do not match")
    session = contract.get("session_partition") or {}
    session_input = summaries.get(roles.get(session.get("role"))) or {}
    if session_input.get("source_action_ref") != roles.get(
        session.get("source_role")
    ):
        raise ValueError("session partition source does not match")
    for field in ("cohorts", "mixed_session_cohort"):
        expected = session.get(
            "required_cohorts" if field == "cohorts" else field
        )
        if session_input.get(field) != expected:
            raise ValueError("session partition contract does not match")


def _validate_run_cohorts(
    value: Any,
    roles: dict[str, str],
    actions: dict[str, dict[str, Any]],
    summaries: Any,
) -> None:
    if not isinstance(value, dict) or not isinstance(summaries, dict):
        raise ValueError("run cohort contract and summaries are required")
    for role, expected in value.items():
        if role not in roles or not isinstance(expected, list):
            raise ValueError("run cohort contract references unknown role")
        action = actions[roles[role]]
        cohorts = {
            (summaries.get(run_hash) or {}).get("session_cohort")
            for run_hash in action.get("run_spec_hashes") or []
        }
        if cohorts != set(expected):
            raise ValueError(
                f"{role} must preserve its declared session cohorts"
            )
