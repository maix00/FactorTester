"""Decision Contract and bounded Research Claim schemas."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..protocol import (
    assert_no_skill_identity,
    json_hash,
    serialize_bounded_trace_evidence,
)


_CLAIM_STATES = {
    "contradicted",
    "inconclusive",
    "supported_in_scope",
    "superseded",
    "unassessed",
    "unknown",
}


def required_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value

def sha256(value: Any, *, field: str) -> str:
    text = required_text(value, field=field).removeprefix("sha256:")
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ValueError(f"{field} must be sha256")
    return text


def string_array(
    value: Any,
    *,
    field: str,
    non_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or (
        non_empty and not value
    ) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        qualifier = "non-empty " if non_empty else ""
        raise ValueError(f"{field} must be a {qualifier}string array")
    return value


def object_value(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def validate_decision_contract(
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Validate and hash the normalized Work Package/branch view."""
    if not isinstance(contract, dict):
        raise ValueError("decision contract must be an object")
    if contract.get("schema_version") != 1:
        raise ValueError("decision contract schema_version must be 1")
    assert_no_skill_identity(contract, location="decision contract")
    value = deepcopy(contract)
    declared_hash = value.pop("contract_hash", "")
    for field in (
        "contract_id",
        "work_package_ref",
        "branch_ref",
        "decision",
        "permitted_use",
    ):
        required_text(value.get(field), field=field)
    for field in ("scope", "search_design", "blocking_policy"):
        object_value(value.get(field), field=field)
    string_array(
        value.get("stopping_rule_refs"),
        field="stopping_rule_refs",
    )
    for field in ("graph_hash", "methodology_hash"):
        value[field] = sha256(value.get(field), field=field)
    computed_hash = json_hash(value)
    if declared_hash and sha256(
        declared_hash,
        field="contract_hash",
    ) != computed_hash:
        raise ValueError("contract_hash mismatch")
    value["contract_hash"] = computed_hash
    serialize_bounded_trace_evidence(value)
    return value


def validate_research_claim(claim: dict[str, Any]) -> dict[str, Any]:
    """Validate one source-free, scope-bound Claim projection."""
    if not isinstance(claim, dict):
        raise ValueError("research claim must be an object")
    if claim.get("schema_version") != 1:
        raise ValueError("research claim schema_version must be 1")
    assert_no_skill_identity(claim, location="research claim")
    value = deepcopy(claim)
    for field in ("claim_id", "claim_ref", "claim_type"):
        required_text(value.get(field), field=field)
    value["contract_hash"] = sha256(
        value.get("contract_hash"),
        field="contract_hash",
    )
    object_value(value.get("scope"), field="scope")
    if value.get("evidence_state") not in _CLAIM_STATES:
        raise ValueError("invalid research claim evidence_state")
    string_array(value.get("evidence_refs"), field="evidence_refs")
    serialize_bounded_trace_evidence(value)
    return value
