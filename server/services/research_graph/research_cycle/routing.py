"""Derive one accepted research route from bounded adjudication events."""

from __future__ import annotations

from typing import Any

from .adjudication import (
    validate_adjudication_decision,
    validate_adjudication_proposal,
)


def accepted_adjudication_action(
    *,
    previous_checkpoint: dict[str, Any] | None,
    events: list[dict[str, Any]],
) -> str | None:
    """Return one v2 action only after its authority accepts the proposal."""
    proposals = {
        item["proposal_hash"]: item
        for item in (
            (previous_checkpoint or {}).get("pending_adjudications") or []
        )
    }
    accepted_actions: set[str] = set()
    for event in events:
        event_type = event.get("event_type")
        if event_type == "adjudication_proposed":
            proposal = validate_adjudication_proposal(event.get("proposal"))
            proposals[proposal["proposal_hash"]] = proposal
            continue
        if event_type != "adjudication_decided":
            continue
        decision = validate_adjudication_decision(event.get("decision"))
        proposal = proposals.get(decision["proposal_hash"])
        if proposal is None:
            raise ValueError(
                "adjudication route decision has no pending proposal"
            )
        if (
            decision["disposition"] == "accepted"
            and proposal["schema_version"] >= 2
        ):
            accepted_actions.add(str(proposal["recommended_action"]))
    if len(accepted_actions) > 1:
        raise ValueError(
            "one transition cannot authorize conflicting research routes"
        )
    return next(iter(accepted_actions), None)


def adjudication_route_guards(action: str | None) -> dict[str, bool]:
    """Return server-owned guards; client booleans cannot override them."""
    return {
        "adjudication_route_bound": action is not None,
        "factor_revision_authorized": action == "revise_factor",
        "next_trial_stage_required": action == "advance_trial_stage",
        "trial_stage_advance_authorized": action == "advance_trial_stage",
    }
