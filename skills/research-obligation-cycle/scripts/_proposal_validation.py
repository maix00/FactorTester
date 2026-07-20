"""Standalone bounded proposal validation for the reference Skill."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


MAX_BYTES = 6000
FORBIDDEN_SKILL_FIELDS = {
    "implementation_id",
    "loaded_skill_ids",
    "provider",
    "skill_name",
    "source_fingerprint",
    "source_path",
}
AUTHORITIES = {
    "deterministic_verifier",
    "human_audit",
    "independent_reviewer",
    "preregistered_rule",
}
RECOMMENDED_ACTIONS = {
    "advance_trial_stage",
    "continue_execution",
    "research_decision",
    "revise_factor",
}


def load_payload(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("proposal must be a JSON object")
    return value


def validate_adjudication(value: dict[str, Any]) -> dict[str, Any]:
    _reject_skill_identity(value)
    schema_version = value.get("schema_version")
    if schema_version not in {1, 2}:
        raise ValueError("schema_version must be 1 or 2")
    for field in ("proposal_id", "proposer_invocation_id"):
        _text(value.get(field), field)
    for field in ("contract_hash", "trial_plan_hash", "methodology_hash"):
        _sha(value.get(field), field)
    _refs(value.get("evidence_refs"), "evidence_refs", required=True)
    claim_delta = _object_array(
        value.get("claim_evidence_delta"),
        "claim_evidence_delta",
    )
    obligation_delta = _object_array(
        value.get("obligation_delta"),
        "obligation_delta",
    )
    _explicit_noop(
        value,
        delta=claim_delta,
        reason_field="claim_delta_noop_reason",
    )
    _explicit_noop(
        value,
        delta=obligation_delta,
        reason_field="obligation_delta_noop_reason",
    )
    for item in claim_delta:
        for field in (
            "claim_id",
            "from_state",
            "to_state",
            "evidence_grade",
        ):
            _text(item.get(field), f"claim_evidence_delta.{field}")
        if not isinstance(item.get("scope"), dict):
            raise ValueError("Claim delta scope must be an object")
    for item in obligation_delta:
        for field in (
            "obligation_id",
            "from_state",
            "to_state",
            "criterion_ref",
        ):
            _text(item.get(field), f"obligation_delta.{field}")
    warrant = value.get("decision_warrant")
    if not isinstance(warrant, dict):
        raise ValueError("decision_warrant must be an object")
    for field in (
        "finding_refs",
        "rule_refs",
        "alternative_refs",
        "limitation_refs",
    ):
        _refs(warrant.get(field), f"decision_warrant.{field}")
    if not isinstance(warrant.get("reentry_predicates"), list):
        raise ValueError("reentry_predicates must be an array")
    if not isinstance(warrant.get("preregistered"), bool):
        raise ValueError("preregistered must be boolean")
    if warrant.get("required_authority") not in AUTHORITIES:
        raise ValueError("invalid required_authority")
    action = value.get("recommended_action")
    if schema_version == 1 and action is not None:
        raise ValueError(
            "recommended_action requires adjudication schema_version 2"
        )
    if schema_version == 2 and action not in RECOMMENDED_ACTIONS:
        raise ValueError("invalid recommended_action")
    return _finish(value)


def validate_obligation_discovery(
    value: dict[str, Any],
) -> dict[str, Any]:
    validated = validate_adjudication(value)
    if validated["claim_evidence_delta"]:
        raise ValueError("obligation discovery must use a Claim no-op")
    deltas = validated["obligation_delta"]
    if not deltas:
        raise ValueError("obligation discovery requires an obligation delta")
    for item in deltas:
        if item["from_state"] != "absent" or item["to_state"] != "open":
            raise ValueError("new obligation delta must be absent -> open")
        obligation = item.get("obligation")
        if not isinstance(obligation, dict):
            raise ValueError("new obligation requires its complete body")
        for field in (
            "obligation_id",
            "obligation_kind",
            "epistemic_question",
            "created_event_ref",
        ):
            _text(obligation.get(field), f"obligation.{field}")
        if obligation["obligation_id"] != item["obligation_id"]:
            raise ValueError("obligation body ID does not match delta")
        if obligation.get("status") != "open":
            raise ValueError("new obligation body status must be open")
        if obligation.get("contract_hash") != validated["contract_hash"]:
            raise ValueError("obligation Contract hash does not match")
        if obligation.get("methodology_hash") != validated["methodology_hash"]:
            raise ValueError("obligation methodology hash does not match")
        _refs(obligation.get("claim_ids"), "obligation.claim_ids", required=True)
        if not isinstance(obligation.get("scope"), dict):
            raise ValueError("obligation scope must be an object")
        if not isinstance(obligation.get("discharge_criterion"), dict):
            raise ValueError("discharge_criterion must be an object")
    return validated


def result(value: dict[str, Any], *, kind: str) -> dict[str, Any]:
    return {
        "valid": True,
        "kind": kind,
        "canonical_hash": value["proposal_hash"],
        "bytes": len(_canonical_bytes(value)),
    }


def _finish(value: dict[str, Any]) -> dict[str, Any]:
    declared = value.get("proposal_hash")
    body = {key: item for key, item in value.items() if key != "proposal_hash"}
    digest = hashlib.sha256(_canonical_bytes(body)).hexdigest()
    if declared not in (None, "") and declared != digest:
        raise ValueError("proposal_hash mismatch")
    result_value = {**body, "proposal_hash": digest}
    encoded = _canonical_bytes(result_value)
    if len(encoded) > MAX_BYTES:
        raise ValueError(f"proposal exceeds {MAX_BYTES} bytes")
    return result_value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _reject_skill_identity(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = sorted(set(value) & FORBIDDEN_SKILL_FIELDS)
        if forbidden:
            raise ValueError(
                "server proposal may not contain Skill identity: "
                + ", ".join(forbidden)
            )
        for item in value.values():
            _reject_skill_identity(item)
    elif isinstance(value, list):
        for item in value:
            _reject_skill_identity(item)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value


def _sha(value: Any, field: str) -> str:
    text = _text(value, field).removeprefix("sha256:")
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{field} must be sha256")
    return text


def _refs(value: Any, field: str, *, required: bool = False) -> list[str]:
    if (
        not isinstance(value, list)
        or (required and not value)
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise ValueError(f"{field} must be a reference array")
    return value


def _object_array(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(
        isinstance(item, dict) for item in value
    ):
        raise ValueError(f"{field} must be an object array")
    return value


def _explicit_noop(
    value: dict[str, Any],
    *,
    delta: list[dict[str, Any]],
    reason_field: str,
) -> None:
    if delta and reason_field in value:
        raise ValueError(f"{reason_field} is allowed only for a no-op")
    if not delta:
        _text(value.get(reason_field), reason_field)
