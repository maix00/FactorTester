"""Agent Flow authority checks at the live Research Cycle write boundary."""

from __future__ import annotations

from typing import Any

from server.services import agent_execution

from .adjudication import (
    validate_adjudication_decision,
    validate_adjudication_proposal,
)
from .closure import (
    validate_search_exhaustion_decision,
    validate_search_exhaustion_proposal,
)
from .contracts import required_text


_PROPOSER_ROLES = {"proposer", "research", "researcher"}
_REVIEWER_ROLE = "reviewer"
_RESEARCH_SCOPE = "local_research"


def validate_live_event_authorities(
    *,
    owner_user_id: str,
    events: list[dict[str, Any]],
    pending_adjudications: list[dict[str, Any]],
    pending_closure: dict[str, Any] | None,
    transition_invocation_ids: list[str],
    store: Any | None = None,
) -> None:
    """Validate one transition's high-risk authority with at most one lookup."""
    proposals = {
        item["proposal_hash"]: item for item in pending_adjudications
    }
    closure = pending_closure
    current_ids: set[str] = set()
    required_ids: set[str] = set()
    review_pairs: list[tuple[str, str, str]] = []

    for event in events:
        event_type = event.get("event_type")
        if event_type == "adjudication_proposed":
            proposal = validate_adjudication_proposal(event.get("proposal"))
            proposer_id = _proposer_id(proposal)
            proposals[proposal["proposal_hash"]] = proposal
            current_ids.add(proposer_id)
            required_ids.add(proposer_id)
        elif event_type == "adjudication_decided":
            decision = validate_adjudication_decision(event.get("decision"))
            if decision["authority_class"] != "independent_reviewer":
                continue
            proposal = proposals.get(decision["proposal_hash"])
            if proposal is None:
                raise ValueError(
                    "independent review has no bound adjudication proposal"
                )
            reviewer_id = str(decision["authority_ref"])
            proposer_id = _proposer_id(proposal)
            current_ids.add(reviewer_id)
            required_ids.update((proposer_id, reviewer_id))
            review_pairs.append((
                proposer_id,
                reviewer_id,
                f"research-cycle-adjudication:{proposal['proposal_hash']}",
            ))
        elif event_type == "closure_proposed":
            closure = validate_search_exhaustion_proposal(
                event.get("proposal")
            )
            proposer_id = _proposer_id(closure)
            current_ids.add(proposer_id)
            required_ids.add(proposer_id)
        elif event_type == "closure_decided":
            decision = validate_search_exhaustion_decision(
                event.get("decision")
            )
            if decision["authority_class"] != "independent_reviewer":
                continue
            if closure is None:
                raise ValueError(
                    "independent review has no bound closure proposal"
                )
            reviewer_id = str(decision["authority_ref"])
            proposer_id = _proposer_id(closure)
            current_ids.add(reviewer_id)
            required_ids.update((proposer_id, reviewer_id))
            review_pairs.append((
                proposer_id,
                reviewer_id,
                f"research-cycle-closure:{closure['proposal_hash']}",
            ))

    if not required_ids:
        return
    recorded_ids = set(transition_invocation_ids)
    missing_current = sorted(current_ids - recorded_ids)
    if missing_current:
        raise ValueError(
            "research cycle Agent invocations are missing from "
            "agent_invocation_ids: " + ", ".join(missing_current)
        )
    execution_store = store or agent_execution.get_store()
    rows = execution_store.load_executions(
        owner_user_id=owner_user_id,
        execution_ids=sorted(required_ids),
    )
    missing = sorted(required_ids - set(rows))
    if missing:
        raise ValueError(
            "research cycle Agent invocation not found: "
            + ", ".join(missing)
        )
    for proposal in proposals.values():
        proposer_id = proposal.get("proposer_invocation_id")
        if proposer_id in required_ids:
            _require_proposer(rows[str(proposer_id)])
    if closure is not None:
        proposer_id = closure.get("proposer_invocation_id")
        if proposer_id in required_ids:
            _require_proposer(rows[str(proposer_id)])
    for proposer_id, reviewer_id, task_ref in review_pairs:
        proposer = rows[proposer_id]
        reviewer = rows[reviewer_id]
        _require_reviewer(reviewer, task_ref=task_ref)
        if (
            proposer["agent_principal_hash"]
            == reviewer["agent_principal_hash"]
            or proposer["lineage_hash"] == reviewer["lineage_hash"]
        ):
            raise ValueError(
                "independent reviewer principal and lineage must differ "
                "from the proposal author"
            )


def _proposer_id(proposal: dict[str, Any]) -> str:
    return required_text(
        proposal.get("proposer_invocation_id"),
        field="proposer_invocation_id",
    )


def _require_proposer(row: dict[str, Any]) -> None:
    if row["status"] != "settled":
        raise ValueError("research cycle proposer execution must be settled")
    if row["actor_role"] not in _PROPOSER_ROLES:
        raise ValueError("research cycle proposer execution has invalid role")
    if row["authority_scope"] != _RESEARCH_SCOPE:
        raise ValueError("research cycle proposer has invalid authority scope")


def _require_reviewer(row: dict[str, Any], *, task_ref: str) -> None:
    if row["status"] != "settled":
        raise ValueError("independent reviewer execution must be settled")
    if row["actor_role"] != _REVIEWER_ROLE:
        raise ValueError("independent reviewer execution has invalid role")
    if row["authority_scope"] != _RESEARCH_SCOPE:
        raise ValueError("independent reviewer has invalid authority scope")
    if row["task_ref"] != task_ref:
        raise ValueError(
            "independent reviewer execution is not bound to the proposal"
        )
