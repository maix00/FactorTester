"""TrialPlan v5 Evidence Action binding at ResearchRun creation."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson

from .execution_checkpoint_contract import (
    validate_checkpoint_plan_identity,
    validate_execution_checkpoint,
)
from .fields import identifier_field, sha256_field


def normalize_v5_run_binding(
    *,
    plan: dict[str, Any],
    run_spec_hash: str,
    trial_role: str,
    comparison_id: str,
    sample_identity: dict[str, Any] | None,
    evidence_action_id: str,
) -> dict[str, Any]:
    """Bind a planned RunSpec to exactly one current Evidence Action."""
    action_id = identifier_field(
        evidence_action_id,
        "trial_binding.evidence_action_id",
    )
    action = next(
        (item for item in plan["evidence_actions"] if item["action_id"] == action_id),
        None,
    )
    if action is None:
        raise ValueError("Evidence Action identity does not match TrialPlan")
    input_hash = action["input_hash"]
    if action["execution_mode"] != "job":
        raise ValueError("ResearchRun requires a job Evidence Action")
    if run_spec_hash not in action["run_spec_hashes"]:
        raise ValueError("RunSpec hash is not declared by Evidence Action")
    if comparison_id not in action["comparison_ids"]:
        raise ValueError("comparison_id is not declared by Evidence Action")
    comparison = next(
        (
            item
            for item in plan["comparisons"]
            if item["comparison_id"] == comparison_id
        ),
        None,
    )
    if comparison is None:
        raise ValueError("comparison_id is not declared by TrialPlan")
    if not any(
        member["run_spec_hash"] == run_spec_hash
        and member["trial_role"] == trial_role
        for member in comparison["members"]
    ):
        raise ValueError(
            "RunSpec hash and trial_role are not a planned comparison member"
        )
    sample = next(
        (
            item
            for item in plan["samples"]
            if run_spec_hash in item["run_spec_hashes"]
        ),
        None,
    )
    if sample is None:
        raise ValueError("RunSpec hash has no declared TrialPlan sample")
    if sample["stage_id"] != action["stage_id"]:
        raise ValueError("RunSpec sample is not in the Evidence Action stage")
    if sample_identity is None:
        raise ValueError(
            "TrialPlan schema_version 5 requires server-derived sample identity"
        )
    if sample["sample_hash"] != sample_identity["sample_hash"]:
        raise ValueError(
            "TrialPlan sample_hash does not match server-derived sample identity"
        )
    return {
        "trial_role": trial_role,
        "trial_stage": str(sample["semantic_role"]),
        "comparison_id": comparison_id,
        "sample_ref": str(sample["sample_ref"]),
        "sample_hash": str(sample["sample_hash"]),
        "sample_identity_assurance": "server_derived_bound",
        "evidence_action_id": action_id,
        "action_input_hash": input_hash,
        "action_stage_id": str(action["stage_id"]),
    }


def validate_v5_action_release(
    *,
    row: Any,
    plan: dict[str, Any],
    evidence_action_id: str,
    action_input_hash: str,
    expected_checkpoint_hash: str,
    expected_latest_trace_id: str,
) -> dict[str, Any]:
    """Validate a released action and return its immutable Run snapshot."""
    checkpoint_json = str(row["trial_stage_projection_json"] or "{}")
    checkpoint = validate_execution_checkpoint(orjson.loads(checkpoint_json))
    validate_checkpoint_plan_identity(checkpoint, plan)
    if checkpoint["execution_node"] != str(row["current_node"]):
        raise ValueError("ResearchRun is not at the Evidence Action execution node")
    if str(row["latest_trace_id"] or "") != expected_latest_trace_id:
        raise ValueError("research branch trace changed before action release")
    if checkpoint["projection_hash"] != sha256_field(
        expected_checkpoint_hash,
        "trial_binding.expected_checkpoint_hash",
    ):
        raise ValueError("execution checkpoint changed before action release")
    if (
        checkpoint["current_action_id"] != evidence_action_id
        or checkpoint["current_action_input_hash"] != action_input_hash
    ):
        raise ValueError("ResearchRun is not bound to the current Evidence Action")
    if checkpoint["current_action_status"] != "released":
        raise ValueError("current Evidence Action is not released")
    action = plan["evidence_actions"][checkpoint["current_action_index"]]
    snapshot = {
        "schema_version": 1,
        "action_id": action["action_id"],
        "action_hash": _hash(action),
        "stage_id": action["stage_id"],
        "input_hash": action["input_hash"],
        "execution_mode": action["execution_mode"],
        "capability_requirement_ref": action["capability_requirement_ref"],
        "expected_evidence_kind": action["expected_evidence_kind"],
        "evidence_contract_ref": action["evidence_contract_ref"],
        "obligation_refs": action["obligation_refs"],
        "run_spec_hashes": action["run_spec_hashes"],
        "comparison_ids": action["comparison_ids"],
        "release_checkpoint_hash": checkpoint["projection_hash"],
    }
    return {
        "evidence_action_binding_json": orjson.dumps(snapshot).decode(),
        "evidence_action_binding_hash": _hash(snapshot),
    }


def _hash(value: Any) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
