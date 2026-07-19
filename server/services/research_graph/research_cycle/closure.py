"""Bounded search-exhaustion and closure protocol."""

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


_DISPOSITIONS = {
    "blocked",
    "decision_ready",
    "exhausted_without_support",
    "stopped_by_resource_boundary",
    "superseded",
}
_DECISION_DISPOSITIONS = {
    "accepted",
    "rejected",
    "revision_requested",
}
_CLOSURE_AUTHORITIES = {
    "human_audit",
    "independent_reviewer",
}


def validate_search_exhaustion_proposal(
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """Validate a defeasible, Contract-scoped bounded-closure proposal."""
    if not isinstance(proposal, dict):
        raise ValueError("search exhaustion proposal must be an object")
    if proposal.get("schema_version") != 1:
        raise ValueError("search exhaustion schema_version must be 1")
    assert_no_skill_identity(proposal, location="search exhaustion proposal")
    value = deepcopy(proposal)
    declared_hash = value.pop("proposal_hash", "")
    required_text(value.get("proposal_id"), field="proposal_id")
    for field in (
        "contract_hash",
        "claim_projection_hash",
        "obligation_projection_hash",
        "graph_hash",
        "methodology_hash",
    ):
        value[field] = sha256(value.get(field), field=field)
    object_value(value.get("coverage_summary"), field="coverage_summary")
    string_array(
        value.get("blocking_obligations"),
        field="blocking_obligations",
    )
    string_array(
        value.get("attempted_trial_refs"),
        field="attempted_trial_refs",
    )
    string_array(
        value.get("discovery_lens_refs"),
        field="discovery_lens_refs",
        non_empty=True,
    )
    for field in (
        "remaining_unknowns",
        "candidate_trial_frontier",
        "frontier_exclusions",
        "reentry_predicates",
    ):
        _object_array(value.get(field), field=field)
    if value.get("disposition") not in _DISPOSITIONS:
        raise ValueError("invalid bounded-closure disposition")
    if value.get("closure_challenge_required") is not True:
        raise ValueError("bounded closure requires one closure challenge")
    if (
        value["disposition"] == "decision_ready"
        and value["blocking_obligations"]
    ):
        raise ValueError(
            "decision_ready cannot retain blocking obligations"
        )
    if (
        value["disposition"] == "decision_ready"
        and value["candidate_trial_frontier"]
    ):
        raise ValueError(
            "decision_ready cannot retain an actionable TrialPlan frontier"
        )
    if not value["reentry_predicates"]:
        raise ValueError("bounded closure requires reentry_predicates")
    computed_hash = json_hash(value)
    if declared_hash and sha256(
        declared_hash,
        field="proposal_hash",
    ) != computed_hash:
        raise ValueError("search exhaustion proposal_hash mismatch")
    value["proposal_hash"] = computed_hash
    serialize_bounded_trace_evidence(value)
    return value


def validate_search_exhaustion_decision(
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Validate the independent challenge decision for bounded closure."""
    if not isinstance(decision, dict):
        raise ValueError("search exhaustion decision must be an object")
    if decision.get("schema_version") != 1:
        raise ValueError("search exhaustion decision schema_version must be 1")
    assert_no_skill_identity(
        decision,
        location="search exhaustion decision",
    )
    value = deepcopy(decision)
    required_text(value.get("decision_id"), field="decision_id")
    value["proposal_hash"] = sha256(
        value.get("proposal_hash"),
        field="proposal_hash",
    )
    value["methodology_hash"] = sha256(
        value.get("methodology_hash"),
        field="methodology_hash",
    )
    if value.get("disposition") not in _DECISION_DISPOSITIONS:
        raise ValueError("invalid search exhaustion decision disposition")
    if value.get("authority_class") not in _CLOSURE_AUTHORITIES:
        raise ValueError("bounded closure requires independent authority")
    required_text(value.get("authority_ref"), field="authority_ref")
    serialize_bounded_trace_evidence(value)
    return value

def _object_array(value: Any, *, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(
        isinstance(item, dict) for item in value
    ):
        raise ValueError(f"{field} must be an object array")
    return value
