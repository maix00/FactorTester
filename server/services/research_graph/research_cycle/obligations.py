"""Extensible Verification Obligation schema."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..protocol import (
    assert_no_skill_identity,
    serialize_bounded_trace_evidence,
)
from .contracts import (
    object_value,
    required_text,
    sha256,
    string_array,
)


_OBLIGATION_STATES = {
    "bounded",
    "discharged",
    "open",
    "rejected",
    "reopened",
    "serviced",
}
_MATERIALITY = {"decision_blocking", "non_blocking"}


def validate_verification_obligation(
    obligation: dict[str, Any],
) -> dict[str, Any]:
    """Validate an obligation without imposing a closed kind ontology."""
    if not isinstance(obligation, dict):
        raise ValueError("verification obligation must be an object")
    if obligation.get("schema_version") != 1:
        raise ValueError("verification obligation schema_version must be 1")
    assert_no_skill_identity(obligation, location="verification obligation")
    value = deepcopy(obligation)
    for field in (
        "obligation_id",
        "obligation_kind",
        "epistemic_question",
        "created_event_ref",
    ):
        required_text(value.get(field), field=field)
    value["contract_hash"] = sha256(
        value.get("contract_hash"),
        field="contract_hash",
    )
    string_array(value.get("claim_ids"), field="claim_ids")
    if "requirement_refs" in value:
        string_array(
            value.get("requirement_refs"),
            field="requirement_refs",
        )
    object_value(value.get("scope"), field="scope")
    object_value(
        value.get("discharge_criterion"),
        field="discharge_criterion",
    )
    if value.get("status") not in _OBLIGATION_STATES:
        raise ValueError("invalid verification obligation status")
    if value.get("materiality") not in _MATERIALITY:
        raise ValueError("invalid verification obligation materiality")
    value["methodology_hash"] = sha256(
        value.get("methodology_hash"),
        field="methodology_hash",
    )
    serialize_bounded_trace_evidence(value)
    return value
