"""Compact mutable cursor for immutable TrialPlan v5 Evidence Actions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .contract import canonical_trial_plan, trial_plan_hash
from .fields import (
    identifier_field,
    identifier_list,
    sha256_field,
)
from .execution_checkpoint_contract import (
    QUALIFICATIONS,
    frozen_design_hash,
    partition_commitment_hash,
    seal_checkpoint,
    validate_checkpoint_plan_identity,
    validate_execution_checkpoint,
    without_checkpoint_hash,
)


MAX_ACTION_EVIDENCE_REFS = 16
_ALLOWED_STATUS_TRANSITIONS = {
    ("unreleased", "released"),
    ("released", "running"),
    ("released", "evidence_ready"),
    ("released", "blocked"),
    ("released", "failed"),
    ("running", "evidence_ready"),
    ("running", "blocked"),
    ("running", "failed"),
    ("blocked", "released"),
    ("evidence_ready", "admitted"),
}


def initial_execution_checkpoint(
    *,
    trial_plan: dict[str, Any],
    expected_trial_plan_hash: str,
    execution_node: str,
) -> dict[str, Any]:
    plan = canonical_trial_plan(trial_plan)
    if plan["schema_version"] != 5:
        raise ValueError("execution checkpoint requires TrialPlan schema v5")
    actual_hash = trial_plan_hash(plan)
    if sha256_field(
        expected_trial_plan_hash,
        "expected_trial_plan_hash",
    ) != actual_hash:
        raise ValueError("TrialPlan hash does not match execution checkpoint")
    if plan["version"] != 1 or plan["parent_trial_plan_hash"] is not None:
        raise ValueError("initial execution checkpoint requires plan version 1")
    return _new_execution_checkpoint(plan, execution_node=execution_node)


def revised_execution_checkpoint(
    *,
    trial_plan: dict[str, Any],
    expected_trial_plan_hash: str,
    previous_trial_plan_hash: str,
    previous_version: int,
    execution_node: str,
) -> dict[str, Any]:
    """Reset an unused Action cursor onto one explicit child TrialPlan."""
    plan = canonical_trial_plan(trial_plan)
    actual_hash = trial_plan_hash(plan)
    if sha256_field(
        expected_trial_plan_hash,
        "expected_trial_plan_hash",
    ) != actual_hash:
        raise ValueError("TrialPlan hash does not match execution checkpoint")
    parent = sha256_field(
        previous_trial_plan_hash,
        "previous_trial_plan_hash",
    )
    if plan["parent_trial_plan_hash"] != parent:
        raise ValueError("revised TrialPlan must name the current plan as parent")
    if plan["version"] != previous_version + 1:
        raise ValueError("revised TrialPlan version must increment by one")
    return _new_execution_checkpoint(plan, execution_node=execution_node)


def _new_execution_checkpoint(
    plan: dict[str, Any],
    *,
    execution_node: str,
) -> dict[str, Any]:
    action = plan["evidence_actions"][0]
    value = {
        "schema_version": 3,
        "trial_plan_id": plan["trial_plan_id"],
        "plan_version": plan["version"],
        "ordered_stage_ids": deepcopy(
            plan["stage_policy"]["ordered_stage_ids"]
        ),
        "current_stage_id": action["stage_id"],
        "completed_stage_mask": 0,
        "partition_commitment_hash": partition_commitment_hash(plan),
        "frozen_design_hash": frozen_design_hash(plan),
        "execution_node": identifier_field(
            execution_node,
            "trial_execution_checkpoint.execution_node",
        ),
        "current_action_index": 0,
        "current_action_id": action["action_id"],
        "current_action_status": "unreleased",
        "current_action_input_hash": action["input_hash"],
        "current_action_output_evidence_refs": [],
        "current_action_qualification": None,
        "current_action_audit_ref": None,
        "current_action_audit_disposition": None,
        "current_action_audit_route": None,
    }
    return seal_checkpoint(value)


def transition_action_status(
    checkpoint: dict[str, Any],
    *,
    target: str,
    evidence_refs: list[str] | None = None,
    qualification: str | None = None,
) -> dict[str, Any]:
    current = validate_execution_checkpoint(checkpoint)
    source = current["current_action_status"]
    if (source, target) not in _ALLOWED_STATUS_TRANSITIONS:
        raise ValueError(f"invalid Evidence Action transition: {source} -> {target}")
    refs = identifier_list(
        evidence_refs or [],
        "trial_execution_checkpoint.current_action_output_evidence_refs",
    )
    if len(refs) > MAX_ACTION_EVIDENCE_REFS:
        raise ValueError(
            "current action may reference at most "
            f"{MAX_ACTION_EVIDENCE_REFS} Evidence objects"
        )
    if target in {"evidence_ready", "admitted", "audited"} and not (
        refs or current["current_action_output_evidence_refs"]
    ):
        raise ValueError(f"{target} requires Evidence references")
    if target == "admitted":
        if qualification not in QUALIFICATIONS:
            raise ValueError("admitted Evidence requires a qualification")
    elif qualification is not None:
        raise ValueError("qualification is assigned only during admission")
    value = without_checkpoint_hash(current)
    value["current_action_status"] = target
    if refs:
        value["current_action_output_evidence_refs"] = refs
    if target == "admitted":
        value["current_action_qualification"] = qualification
    return seal_checkpoint(value)


def advance_after_audit(
    checkpoint: dict[str, Any],
    *,
    trial_plan: dict[str, Any],
) -> dict[str, Any]:
    current = validate_execution_checkpoint(checkpoint)
    plan = validate_checkpoint_plan_identity(current, trial_plan)
    if current["current_action_status"] != "audited":
        raise ValueError("next Evidence Action requires an audited predecessor")
    if current["current_action_qualification"] not in {"eligible", "limited"}:
        raise ValueError("next Evidence Action requires usable admitted Evidence")
    if current["current_action_audit_disposition"] != "accepted":
        raise ValueError("next Evidence Action requires an accepted result audit")
    if current["current_action_audit_route"] not in {
        "continue_execution", "advance_trial_stage",
    }:
        raise ValueError("result audit does not authorize the next Evidence Action")
    next_index = current["current_action_index"] + 1
    actions = plan["evidence_actions"]
    if next_index >= len(actions):
        raise ValueError("TrialPlan has no next Evidence Action")
    action = actions[next_index]
    completed = current["completed_stage_mask"]
    if action["stage_id"] != current["current_stage_id"]:
        stage_index = current["ordered_stage_ids"].index(
            current["current_stage_id"]
        )
        completed |= 1 << stage_index
    value = without_checkpoint_hash(current)
    value.update({
        "current_stage_id": action["stage_id"],
        "completed_stage_mask": completed,
        "current_action_index": next_index,
        "current_action_id": action["action_id"],
        "current_action_status": "unreleased",
        "current_action_input_hash": action["input_hash"],
        "current_action_output_evidence_refs": [],
        "current_action_qualification": None,
        "current_action_audit_ref": None,
        "current_action_audit_disposition": None,
        "current_action_audit_route": None,
    })
    return seal_checkpoint(value)


def agent_action_summary(checkpoint: dict[str, Any]) -> dict[str, Any]:
    value = validate_execution_checkpoint(checkpoint)
    return {
        "action_id": value["current_action_id"],
        "status": value["current_action_status"],
        "stage_id": value["current_stage_id"],
        "input_hash": value["current_action_input_hash"],
        "qualification": value["current_action_qualification"],
        "evidence_refs": value["current_action_output_evidence_refs"],
    }
