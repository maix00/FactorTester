"""Exact reuse of previously admitted Evidence without rerunning a Job."""

from __future__ import annotations

from typing import Any

from ..protocol import json_hash
from .execution_checkpoint import transition_action_status
from .execution_checkpoint_contract import (
    validate_checkpoint_plan_identity,
    validate_execution_checkpoint,
)


_RECEIPT_FIELDS = {
    "schema_version", "trial_plan_hash", "action_id", "stage_id",
    "action_input_hash", "evidence_contract_ref", "expected_evidence_kind",
    "run_spec_hashes", "evidence_refs", "qualification", "receipt_hash",
}


def reuse_exact_action_evidence(
    checkpoint: dict[str, Any],
    *,
    trial_plan: dict[str, Any],
    admission_receipt: dict[str, Any],
) -> dict[str, Any]:
    """Release evidence_ready only for an unchanged, eligible Action identity."""
    current = validate_execution_checkpoint(checkpoint)
    plan = validate_checkpoint_plan_identity(current, trial_plan)
    if current["current_action_status"] != "unreleased":
        raise ValueError("exact Evidence reuse requires an unreleased action")
    receipt = _validate_receipt(admission_receipt)
    action = plan["evidence_actions"][current["current_action_index"]]
    expected = {
        "trial_plan_hash": json_hash(plan),
        "action_id": action["action_id"],
        "stage_id": action["stage_id"],
        "action_input_hash": action["input_hash"],
        "evidence_contract_ref": action["evidence_contract_ref"],
        "expected_evidence_kind": action["expected_evidence_kind"],
        "run_spec_hashes": sorted(action["run_spec_hashes"]),
    }
    if any(receipt[field] != value for field, value in expected.items()):
        raise ValueError("admitted Evidence is not an exact Action match")
    if receipt["qualification"] != "eligible":
        raise ValueError("only eligible Evidence supports exact reuse")
    released = transition_action_status(current, target="released")
    ready = transition_action_status(
        released,
        target="evidence_ready",
        evidence_refs=receipt["evidence_refs"],
    )
    return {
        "schema_version": 1,
        "reuse": "exact",
        "source_admission_receipt_hash": receipt["receipt_hash"],
        "evidence_refs": receipt["evidence_refs"],
        "checkpoint": ready,
    }


def _validate_receipt(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _RECEIPT_FIELDS:
        raise ValueError("admission receipt has invalid fields")
    receipt = dict(value)
    declared_hash = receipt.pop("receipt_hash")
    if receipt.get("schema_version") != 1 or declared_hash != json_hash(receipt):
        raise ValueError("admission receipt hash mismatch")
    for field in ("run_spec_hashes", "evidence_refs"):
        items = receipt.get(field)
        if not isinstance(items, list) or not items or len(items) != len(set(items)):
            raise ValueError(f"admission receipt {field} is invalid")
    return {**receipt, "receipt_hash": declared_hash}
