"""Paired Claim/obligation adjudication protocol."""

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


_CLAIM_STATES = {
    "contradicted",
    "inconclusive",
    "supported_in_scope",
    "superseded",
    "unassessed",
    "unknown",
}
_OBLIGATION_STATES = {
    "absent",
    "bounded",
    "discharged",
    "open",
    "rejected",
    "reopened",
    "serviced",
}
_EVIDENCE_GRADES = {
    "deterministic",
    "exploratory",
    "preregistered",
    "reviewer_adjudicated",
}
_INFERENCE_TYPES = {
    "conflicting",
    "deterministic",
    "non_standard",
    "post_hoc",
    "preregistered",
    "semantic",
}
_AUTHORITIES = {
    "deterministic_verifier",
    "human_audit",
    "independent_reviewer",
    "preregistered_rule",
}
_DISPOSITIONS = {"accepted", "rejected", "revision_requested"}
_RECOMMENDED_ACTIONS = {
    "advance_trial_stage",
    "continue_execution",
    "research_decision",
    "revise_factor",
}


def validate_adjudication_proposal(
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """Validate paired deltas and produce a canonical proposal hash."""
    if not isinstance(proposal, dict):
        raise ValueError("adjudication proposal must be an object")
    schema_version = proposal.get("schema_version")
    if schema_version not in {1, 2}:
        raise ValueError(
            "adjudication proposal schema_version must be 1 or 2"
        )
    assert_no_skill_identity(proposal, location="adjudication proposal")
    value = deepcopy(proposal)
    declared_hash = value.pop("proposal_hash", "")
    required_text(value.get("proposal_id"), field="proposal_id")
    if "proposer_invocation_id" in value:
        required_text(
            value.get("proposer_invocation_id"),
            field="proposer_invocation_id",
        )
    value["contract_hash"] = sha256(
        value.get("contract_hash"),
        field="contract_hash",
    )
    value["trial_plan_hash"] = sha256(
        value.get("trial_plan_hash"),
        field="trial_plan_hash",
    )
    value["methodology_hash"] = sha256(
        value.get("methodology_hash"),
        field="methodology_hash",
    )
    string_array(
        value.get("evidence_refs"),
        field="evidence_refs",
        non_empty=True,
    )
    value["claim_evidence_delta"] = _claim_deltas(
        value.get("claim_evidence_delta")
    )
    value["obligation_delta"] = _obligation_deltas(
        value.get("obligation_delta")
    )
    _require_explicit_noop(
        value,
        delta_field="claim_evidence_delta",
        reason_field="claim_delta_noop_reason",
    )
    _require_explicit_noop(
        value,
        delta_field="obligation_delta",
        reason_field="obligation_delta_noop_reason",
    )
    value["decision_warrant"] = _decision_warrant(
        value.get("decision_warrant")
    )
    recommended_action = value.get("recommended_action")
    if schema_version == 1 and recommended_action is not None:
        raise ValueError(
            "recommended_action requires adjudication schema_version 2"
        )
    if (
        schema_version == 2
        and recommended_action not in _RECOMMENDED_ACTIONS
    ):
        raise ValueError("invalid adjudication recommended_action")
    computed_hash = json_hash(value)
    if declared_hash and sha256(
        declared_hash,
        field="proposal_hash",
    ) != computed_hash:
        raise ValueError("proposal_hash mismatch")
    value["proposal_hash"] = computed_hash
    serialize_bounded_trace_evidence(value)
    return value


def validate_adjudication_decision(
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Validate an authority-bearing disposition bound to one proposal."""
    if not isinstance(decision, dict):
        raise ValueError("adjudication decision must be an object")
    if decision.get("schema_version") != 1:
        raise ValueError("adjudication decision schema_version must be 1")
    assert_no_skill_identity(decision, location="adjudication decision")
    value = deepcopy(decision)
    required_text(value.get("decision_id"), field="decision_id")
    value["proposal_hash"] = sha256(
        value.get("proposal_hash"),
        field="proposal_hash",
    )
    if value.get("disposition") not in _DISPOSITIONS:
        raise ValueError("invalid adjudication disposition")
    if value.get("authority_class") not in _AUTHORITIES:
        raise ValueError("invalid adjudication authority_class")
    required_text(value.get("authority_ref"), field="authority_ref")
    value["methodology_hash"] = sha256(
        value.get("methodology_hash"),
        field="methodology_hash",
    )
    serialize_bounded_trace_evidence(value)
    return value


def validate_adjudication_pair(
    proposal: dict[str, Any],
    decision: dict[str, Any],
    *,
    expected_contract_hash: str,
    expected_trial_plan_hash: str,
    expected_methodology_hash: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind one accepted decision to the current design and required authority."""
    validated_proposal = validate_adjudication_proposal(proposal)
    validated_decision = validate_adjudication_decision(decision)
    expected = {
        "contract_hash": sha256(
            expected_contract_hash,
            field="expected_contract_hash",
        ),
        "trial_plan_hash": sha256(
            expected_trial_plan_hash,
            field="expected_trial_plan_hash",
        ),
        "methodology_hash": sha256(
            expected_methodology_hash,
            field="expected_methodology_hash",
        ),
    }
    if validated_proposal["contract_hash"] != expected["contract_hash"]:
        raise ValueError("Decision Contract hash is stale")
    if validated_proposal["trial_plan_hash"] != expected["trial_plan_hash"]:
        raise ValueError("TrialPlan hash is stale")
    if (
        validated_proposal["methodology_hash"]
        != expected["methodology_hash"]
        or validated_decision["methodology_hash"]
        != expected["methodology_hash"]
    ):
        raise ValueError("methodology hash is stale")
    if validated_decision["proposal_hash"] != validated_proposal["proposal_hash"]:
        raise ValueError("decision does not bind the proposal")
    required_authority = validated_proposal[
        "decision_warrant"
    ]["required_authority"]
    if validated_decision["authority_class"] != required_authority:
        raise ValueError("decision authority does not satisfy warrant")
    return validated_proposal, validated_decision


def _claim_deltas(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("claim_evidence_delta must be an array")
    for item in value:
        object_value(item, field="claim_evidence_delta item")
        required_text(item.get("claim_id"), field="claim_id")
        if item.get("from_state") not in _CLAIM_STATES:
            raise ValueError("invalid Claim delta from_state")
        if item.get("to_state") not in _CLAIM_STATES:
            raise ValueError("invalid Claim delta to_state")
        if item.get("evidence_grade") not in _EVIDENCE_GRADES:
            raise ValueError("invalid Claim delta evidence_grade")
        object_value(item.get("scope"), field="Claim delta scope")
    return value


def _obligation_deltas(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("obligation_delta must be an array")
    for item in value:
        object_value(item, field="obligation_delta item")
        required_text(item.get("obligation_id"), field="obligation_id")
        if item.get("from_state") not in _OBLIGATION_STATES:
            raise ValueError("invalid obligation delta from_state")
        if item.get("to_state") not in _OBLIGATION_STATES:
            raise ValueError("invalid obligation delta to_state")
        required_text(item.get("criterion_ref"), field="criterion_ref")
    return value


def _require_explicit_noop(
    value: dict[str, Any],
    *,
    delta_field: str,
    reason_field: str,
) -> None:
    if value[delta_field]:
        if reason_field in value:
            raise ValueError(f"{reason_field} is allowed only for a no-op")
        return
    required_text(value.get(reason_field), field=reason_field)


def _decision_warrant(value: Any) -> dict[str, Any]:
    warrant = object_value(value, field="decision_warrant")
    for field in (
        "finding_refs",
        "rule_refs",
        "alternative_refs",
        "limitation_refs",
    ):
        string_array(warrant.get(field), field=f"decision_warrant.{field}")
    predicates = warrant.get("reentry_predicates")
    if not isinstance(predicates, list) or not all(
        isinstance(item, dict) for item in predicates
    ):
        raise ValueError(
            "decision_warrant.reentry_predicates must be an object array"
        )
    if warrant.get("inference_type") not in _INFERENCE_TYPES:
        raise ValueError("invalid decision_warrant.inference_type")
    if not isinstance(warrant.get("preregistered"), bool):
        raise ValueError("decision_warrant.preregistered must be boolean")
    if warrant.get("required_authority") not in _AUTHORITIES:
        raise ValueError("invalid decision_warrant.required_authority")
    if (
        warrant.get("inference_type") == "post_hoc"
        and warrant.get("required_authority") == "preregistered_rule"
    ):
        raise ValueError(
            "post_hoc inference cannot use preregistered_rule authority"
        )
    return warrant
