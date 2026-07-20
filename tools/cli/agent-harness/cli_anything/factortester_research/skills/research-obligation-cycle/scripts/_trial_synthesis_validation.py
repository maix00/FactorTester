"""Validate one local selective TrialPlan-synthesis decision."""

from __future__ import annotations

import hashlib
from typing import Any

from _proposal_validation import (
    MAX_BYTES,
    _canonical_bytes,
    _object_array,
    _refs,
    _reject_skill_identity,
    _sha,
    _text,
)


ASSESSMENTS = {
    "actionable_trial",
    "semantic_resolution",
    "provenance_repair",
    "backend_gap",
    "infeasible",
    "bounded_unknown",
}
OUTPUTS = {
    "trial_plan",
    "no_actionable_trial",
    "capability_gap",
    "provisional_outline",
}


def validate_trial_synthesis(value: dict[str, Any]) -> dict[str, Any]:
    """Ensure canonical plans select only explicitly actionable obligations."""
    _reject_skill_identity(value)
    if value.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    _sha(value.get("decision_contract_hash"), "decision_contract_hash")
    _sha(value.get("methodology_hash"), "methodology_hash")
    assessments = _object_array(
        value.get("obligation_assessments"),
        "obligation_assessments",
    )
    if not assessments:
        raise ValueError("obligation_assessments must not be empty")
    ids: set[str] = set()
    actionable: set[str] = set()
    for item in assessments:
        obligation_id = _text(
            item.get("obligation_id"),
            "assessment.obligation_id",
        )
        if obligation_id in ids:
            raise ValueError("obligation assessment IDs must be unique")
        ids.add(obligation_id)
        disposition = item.get("disposition")
        if disposition not in ASSESSMENTS:
            raise ValueError("invalid obligation assessment disposition")
        _text(item.get("reason_ref"), "assessment.reason_ref")
        if disposition == "actionable_trial":
            actionable.add(obligation_id)
    output = value.get("output")
    if not isinstance(output, dict):
        raise ValueError("output must be an object")
    disposition = output.get("disposition")
    if disposition not in OUTPUTS:
        raise ValueError("invalid synthesis output disposition")
    if disposition == "trial_plan":
        _validate_trial_plan_output(output, actionable)
    elif disposition == "no_actionable_trial":
        if actionable:
            raise ValueError(
                "no_actionable_trial conflicts with actionable obligations"
            )
        _forbid_trial_plan(output)
        _text(output.get("reason_ref"), "output.reason_ref")
    elif disposition == "capability_gap":
        _forbid_trial_plan(output)
        _refs(
            output.get("capability_gap_refs"),
            "output.capability_gap_refs",
            required=True,
        )
    else:
        _forbid_trial_plan(output)
        _text(output.get("outline_ref"), "output.outline_ref")
    body = {
        key: item for key, item in value.items() if key != "synthesis_hash"
    }
    synthesis_hash = hashlib.sha256(_canonical_bytes(body)).hexdigest()
    declared = value.get("synthesis_hash")
    if declared not in (None, "") and declared != synthesis_hash:
        raise ValueError("synthesis_hash mismatch")
    validated = {**body, "synthesis_hash": synthesis_hash}
    if len(_canonical_bytes(validated)) > MAX_BYTES:
        raise ValueError(f"trial synthesis exceeds {MAX_BYTES} bytes")
    return validated


def validation_result(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "valid": True,
        "kind": "trial_synthesis",
        "disposition": value["output"]["disposition"],
        "canonical_hash": value["synthesis_hash"],
        "bytes": len(_canonical_bytes(value)),
    }


def _validate_trial_plan_output(
    output: dict[str, Any],
    actionable: set[str],
) -> None:
    plan = output.get("trial_plan")
    if not isinstance(plan, dict):
        raise ValueError("trial_plan output requires a plan object")
    refs = set(_refs(
        plan.get("obligation_refs"),
        "trial_plan.obligation_refs",
        required=True,
    ))
    invalid = sorted(refs - actionable)
    if invalid:
        raise ValueError(
            "trial plan references a non-actionable obligation: "
            + ", ".join(invalid)
        )


def _forbid_trial_plan(output: dict[str, Any]) -> None:
    if "trial_plan" in output:
        raise ValueError("non-trial output must not contain trial_plan")
