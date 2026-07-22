"""Deterministic admission of Evidence for one TrialPlan v5 action."""

from __future__ import annotations

from typing import Any

from ..protocol import json_hash
from ..research_cycle.evidence import validate_agent_evidence_envelope
from .execution_checkpoint import transition_action_status
from .execution_checkpoint_contract import (
    validate_checkpoint_plan_identity,
    validate_execution_checkpoint,
)


def admit_current_action(
    checkpoint: dict[str, Any],
    *,
    trial_plan: dict[str, Any],
    evidence_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Qualify a complete job Action without semantic interpretation."""
    current = validate_execution_checkpoint(checkpoint)
    plan = validate_checkpoint_plan_identity(current, trial_plan)
    if current["current_action_status"] != "evidence_ready":
        raise ValueError("Evidence admission requires an evidence_ready action")
    action = plan["evidence_actions"][current["current_action_index"]]
    if action["execution_mode"] != "job":
        raise ValueError("job Evidence admission requires a job Action")
    expected_runs = set(action["run_spec_hashes"])
    observed: dict[str, dict[str, Any]] = {}
    evidence_refs: list[str] = []
    rejection_codes: set[str] = set()
    for index, raw in enumerate(evidence_records):
        run_hash, envelope = _validate_record(
            raw,
            index=index,
            plan=plan,
            action=action,
        )
        if run_hash in observed:
            raise ValueError("Evidence admission contains a duplicate RunSpec")
        observed[run_hash] = envelope
        evidence_ref = "evidence:" + envelope["envelope_hash"]
        evidence_refs.append(evidence_ref)
        facts = envelope["facts"]
        assurance = facts["assurance"]
        if facts["status"] != "succeeded":
            rejection_codes.add("job_not_succeeded")
        if assurance["disposition"] != "trusted":
            rejection_codes.add("terminal_assurance_untrusted")
        if assurance["anomaly_codes"]:
            rejection_codes.add("terminal_assurance_anomaly")
    if set(observed) != expected_runs:
        missing = sorted(expected_runs - set(observed))
        extra = sorted(set(observed) - expected_runs)
        raise ValueError(
            "Evidence admission RunSpec set mismatch"
            + (f"; missing={','.join(missing)}" if missing else "")
            + (f"; extra={','.join(extra)}" if extra else "")
        )
    if set(evidence_refs) != set(current["current_action_output_evidence_refs"]):
        raise ValueError("Evidence refs do not match the execution checkpoint")
    qualification = "rejected" if rejection_codes else "eligible"
    admitted = transition_action_status(
        current,
        target="admitted",
        qualification=qualification,
    )
    receipt = {
        "schema_version": 1,
        "trial_plan_hash": json_hash(plan),
        "action_id": action["action_id"],
        "stage_id": action["stage_id"],
        "action_input_hash": action["input_hash"],
        "evidence_contract_ref": action["evidence_contract_ref"],
        "expected_evidence_kind": action["expected_evidence_kind"],
        "run_spec_hashes": sorted(action["run_spec_hashes"]),
        "evidence_refs": sorted(evidence_refs),
        "qualification": qualification,
    }
    return {
        "schema_version": 1,
        "action_id": action["action_id"],
        "qualification": qualification,
        "evidence_refs": sorted(evidence_refs),
        "reason_codes": sorted(rejection_codes),
        "admission_receipt": {
            **receipt,
            "receipt_hash": json_hash(receipt),
        },
        "checkpoint": admitted,
    }


def _validate_record(
    value: Any,
    *,
    index: int,
    plan: dict[str, Any],
    action: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != {"trial_binding", "envelope"}:
        raise ValueError(f"evidence_records[{index}] has invalid fields")
    binding = value["trial_binding"]
    if not isinstance(binding, dict):
        raise ValueError(f"evidence_records[{index}].trial_binding is invalid")
    snapshot = binding.get("evidence_action_binding")
    if not isinstance(snapshot, dict):
        raise ValueError("Evidence lacks an immutable Action binding")
    if binding.get("evidence_action_binding_hash") != json_hash(snapshot):
        raise ValueError("Evidence Action binding hash mismatch")
    if (
        binding.get("trial_plan_hash") != json_hash(plan)
        or binding.get("trial_plan_schema_version") != 5
        or binding.get("trial_stage_id") != action["stage_id"]
        or binding.get("evidence_action_id") != action["action_id"]
        or snapshot.get("action_hash") != json_hash(action)
        or snapshot.get("input_hash") != action["input_hash"]
        or snapshot.get("evidence_contract_ref")
        != action["evidence_contract_ref"]
    ):
        raise ValueError("Evidence does not match the current Action")
    envelope = validate_agent_evidence_envelope(value["envelope"])
    if envelope["evidence_kind"] != "job_attempt":
        raise ValueError("job Action requires JobAttempt Evidence")
    run_hash = envelope["identity_refs"]["run_spec_hash"]
    if run_hash not in action["run_spec_hashes"]:
        raise ValueError("Evidence RunSpec is not declared by current Action")
    if envelope["identity_refs"]["trial_plan_hash"] != json_hash(plan):
        raise ValueError("Evidence TrialPlan identity is stale")
    return run_hash, envelope
