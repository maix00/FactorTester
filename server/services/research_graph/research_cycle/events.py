"""Atomic Research Cycle event application."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..protocol import (
    assert_no_skill_identity,
    json_hash,
)
from .adjudication import (
    validate_adjudication_decision,
    validate_adjudication_pair,
    validate_adjudication_proposal,
)
from .closure import (
    validate_search_exhaustion_decision,
    validate_search_exhaustion_proposal,
)
from .contracts import sha256
from .obligations import validate_verification_obligation


_EVENT_TYPES = {
    "adjudication_decided",
    "adjudication_proposed",
    "closure_decided",
    "closure_proposed",
    "trial_plan_bound",
    "trial_plan_released",
}


def apply_research_cycle_event(
    checkpoint: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    """Apply one validated event on a copy of the current checkpoint."""
    if not isinstance(event, dict):
        raise ValueError("research cycle event must be an object")
    assert_no_skill_identity(event, location="research cycle event")
    event_type = event.get("event_type")
    if event_type not in _EVENT_TYPES:
        raise ValueError("unsupported research cycle event_type")
    value = deepcopy(checkpoint)
    if event_type == "trial_plan_bound":
        return _bind_trial_plan(value, event)
    if event_type == "trial_plan_released":
        return _release_trial_plan(value, event)
    if event_type == "adjudication_proposed":
        return _propose_adjudication(value, event)
    if event_type == "adjudication_decided":
        return _decide_adjudication(value, event)
    if event_type == "closure_proposed":
        return _propose_closure(value, event)
    return _decide_closure(value, event)


def _bind_trial_plan(
    checkpoint: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    from_hash = event.get("from_hash", "")
    if from_hash != checkpoint["trial_plan_hash"]:
        raise ValueError("TrialPlan binding does not match checkpoint")
    if checkpoint["pending_adjudications"]:
        raise ValueError("cannot change TrialPlan with pending adjudication")
    checkpoint["trial_plan_hash"] = sha256(
        event.get("to_hash"),
        field="trial_plan_bound.to_hash",
    )
    return checkpoint


def _release_trial_plan(
    checkpoint: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    if event.get("reason") != "new_hypothesis_lineage":
        raise ValueError("TrialPlan release reason is invalid")
    if event.get("from_hash") != checkpoint["trial_plan_hash"]:
        raise ValueError("TrialPlan release does not match checkpoint")
    if not checkpoint["trial_plan_hash"]:
        raise ValueError("TrialPlan release requires a current plan")
    if checkpoint["pending_adjudications"]:
        raise ValueError(
            "cannot release TrialPlan with pending adjudication"
        )
    checkpoint["trial_plan_hash"] = ""
    return checkpoint


def _propose_adjudication(
    checkpoint: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    payload = event.get("proposal")
    if not isinstance(payload, dict):
        raise ValueError("adjudication proposal event requires proposal")
    proposal = validate_adjudication_proposal(payload)
    if (
        proposal["contract_hash"] != checkpoint["contract_hash"]
        or proposal["trial_plan_hash"] != checkpoint["trial_plan_hash"]
        or proposal["methodology_hash"] != checkpoint["methodology_hash"]
    ):
        raise ValueError("adjudication proposal identity is stale")
    if any(
        item["proposal_hash"] == proposal["proposal_hash"]
        for item in checkpoint["pending_adjudications"]
    ):
        raise ValueError("adjudication proposal is already pending")
    checkpoint["pending_adjudications"].append(proposal)
    return checkpoint


def _decide_adjudication(
    checkpoint: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    payload = event.get("decision")
    if not isinstance(payload, dict):
        raise ValueError("adjudication decision event requires decision")
    decision = validate_adjudication_decision(payload)
    proposal = next(
        (
            item
            for item in checkpoint["pending_adjudications"]
            if item["proposal_hash"] == decision["proposal_hash"]
        ),
        None,
    )
    if proposal is None:
        raise ValueError("adjudication decision has no pending proposal")
    validate_adjudication_pair(
        proposal,
        decision,
        expected_contract_hash=checkpoint["contract_hash"],
        expected_trial_plan_hash=checkpoint["trial_plan_hash"],
        expected_methodology_hash=checkpoint["methodology_hash"],
    )
    if decision["disposition"] == "accepted":
        _apply_accepted_deltas(checkpoint, proposal)
    checkpoint["pending_adjudications"] = [
        item
        for item in checkpoint["pending_adjudications"]
        if item["proposal_hash"] != decision["proposal_hash"]
    ]
    return checkpoint


def _apply_accepted_deltas(
    checkpoint: dict[str, Any],
    proposal: dict[str, Any],
) -> None:
    claims = {item["claim_id"]: item for item in checkpoint["claims"]}
    obligations = {
        item["obligation_id"]: item for item in checkpoint["obligations"]
    }
    invalidates_closure = False
    for delta in proposal["claim_evidence_delta"]:
        claim = claims.get(delta["claim_id"])
        if claim is None or claim["evidence_state"] != delta["from_state"]:
            raise ValueError("Claim delta does not match current projection")
        if claim["scope"] != delta["scope"]:
            raise ValueError("Claim delta scope does not match projection")
        claim["evidence_state"] = delta["to_state"]
        claim["evidence_refs"] = list(dict.fromkeys([
            *claim["evidence_refs"],
            *proposal["evidence_refs"],
        ]))
    for delta in proposal["obligation_delta"]:
        obligation = obligations.get(delta["obligation_id"])
        if obligation is None:
            if delta["from_state"] != "absent":
                raise ValueError(
                    "obligation delta references an unknown obligation"
                )
            payload = delta.get("obligation")
            if not isinstance(payload, dict):
                raise ValueError(
                    "new obligation delta requires the obligation body"
                )
            obligation = validate_verification_obligation(payload)
            if (
                obligation["obligation_id"] != delta["obligation_id"]
                or obligation["status"] != delta["to_state"]
                or obligation["contract_hash"] != checkpoint["contract_hash"]
                or obligation["methodology_hash"]
                != checkpoint["methodology_hash"]
                or not set(obligation["claim_ids"]).issubset(claims)
            ):
                raise ValueError(
                    "new obligation body does not match current projection"
                )
            checkpoint["obligations"].append(obligation)
            obligations[obligation["obligation_id"]] = obligation
            invalidates_closure = (
                invalidates_closure
                or (
                    obligation["materiality"] == "decision_blocking"
                    and obligation["status"] in {"open", "reopened"}
                )
            )
            continue
        if delta["from_state"] == "absent":
            raise ValueError(
                "new obligation conflicts with current projection"
            )
        if obligation["status"] != delta["from_state"]:
            raise ValueError(
                "obligation delta does not match current projection"
            )
        obligation["status"] = delta["to_state"]
        invalidates_closure = (
            invalidates_closure
            or (
                obligation["materiality"] == "decision_blocking"
                and obligation["status"] in {"open", "reopened"}
            )
        )
    if invalidates_closure:
        checkpoint["closure"] = None
        checkpoint["pending_closure"] = None


def _propose_closure(
    checkpoint: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    if checkpoint["pending_closure"] is not None:
        raise ValueError("search exhaustion proposal is already pending")
    payload = event.get("proposal")
    if not isinstance(payload, dict):
        raise ValueError("closure proposal event requires proposal")
    proposal = validate_search_exhaustion_proposal(payload)
    if (
        proposal["contract_hash"] != checkpoint["contract_hash"]
        or proposal["methodology_hash"] != checkpoint["methodology_hash"]
    ):
        raise ValueError("search exhaustion proposal identity is stale")
    if proposal["claim_projection_hash"] != json_hash(checkpoint["claims"]):
        raise ValueError("search exhaustion Claim projection is stale")
    if (
        proposal["obligation_projection_hash"]
        != json_hash(checkpoint["obligations"])
    ):
        raise ValueError("search exhaustion obligation projection is stale")
    blocking = sorted(
        item["obligation_id"]
        for item in checkpoint["obligations"]
        if item["materiality"] == "decision_blocking"
        and item["status"] in {"open", "reopened"}
    )
    if sorted(proposal["blocking_obligations"]) != blocking:
        raise ValueError("search exhaustion blocking obligations are stale")
    checkpoint["pending_closure"] = proposal
    return checkpoint


def _decide_closure(
    checkpoint: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    proposal = checkpoint["pending_closure"]
    if proposal is None:
        raise ValueError("closure decision has no pending proposal")
    payload = event.get("decision")
    if not isinstance(payload, dict):
        raise ValueError("closure decision event requires decision")
    decision = validate_search_exhaustion_decision(payload)
    if decision["proposal_hash"] != proposal["proposal_hash"]:
        raise ValueError("closure decision does not bind the proposal")
    if decision["methodology_hash"] != checkpoint["methodology_hash"]:
        raise ValueError("closure decision methodology is stale")
    if decision["disposition"] == "accepted":
        checkpoint["closure"] = proposal
    checkpoint["pending_closure"] = None
    return checkpoint
