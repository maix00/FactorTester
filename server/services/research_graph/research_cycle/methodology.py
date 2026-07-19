"""Skill-neutral methodology-change protocol."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..protocol import (
    assert_no_skill_identity,
    json_hash,
    serialize_bounded_trace_evidence,
)
from .contracts import (
    object_value,
    required_text,
    sha256,
    string_array,
)


_COMPATIBILITY = {
    "implementation_only",
    "semantic_change",
}


def validate_methodology_change_proposal(
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """Validate a bounded semantic diff without concrete Skill identity."""
    if not isinstance(proposal, dict):
        raise ValueError("methodology change proposal must be an object")
    if proposal.get("schema_version") != 1:
        raise ValueError("methodology change schema_version must be 1")
    assert_no_skill_identity(
        proposal,
        location="methodology change proposal",
    )
    value = deepcopy(proposal)
    declared_hash = value.pop("proposal_hash", "")
    required_text(value.get("proposal_id"), field="proposal_id")
    for field in (
        "current_descriptor_hash",
        "proposed_descriptor_hash",
        "rollback_descriptor_hash",
    ):
        value[field] = sha256(value.get(field), field=field)
    object_value(value.get("semantic_diff"), field="semantic_diff")
    object_value(
        value.get("affected_contract_predicate"),
        field="affected_contract_predicate",
    )
    object_value(value.get("expected_cost"), field="expected_cost")
    for field in (
        "evidence_refs",
        "counterexample_refs",
        "validation_refs",
        "failed_case_refs",
        "implementation_validation_refs",
    ):
        string_array(value.get(field), field=field)
    if value.get("compatibility") not in _COMPATIBILITY:
        raise ValueError("invalid methodology compatibility")
    computed_hash = json_hash(value)
    if declared_hash and sha256(
        declared_hash,
        field="proposal_hash",
    ) != computed_hash:
        raise ValueError("methodology proposal_hash mismatch")
    value["proposal_hash"] = computed_hash
    serialize_bounded_trace_evidence(value)
    return value
