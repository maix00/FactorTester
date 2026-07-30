"""Semantic acceptance tests for bounded Research Cycle closure."""

from __future__ import annotations

from copy import deepcopy

from server.services.research_graph.protocol import json_hash
from server.services.research_graph.research_cycle.closure import (
    validate_search_exhaustion_decision,
    validate_search_exhaustion_proposal,
)
from server.services.research_graph.research_cycle.replay import (
    replay_research_cycle_events,
    validate_research_cycle_checkpoint,
)


def _open_checkpoint() -> dict:
    return validate_research_cycle_checkpoint({
        "schema_version": 1,
        "contract_hash": "1" * 64,
        "trial_plan_hash": "2" * 64,
        "methodology_hash": "3" * 64,
        "claims": [{
            "schema_version": 1,
            "claim_id": "claim-1",
            "contract_hash": "1" * 64,
            "claim_ref": "factor-claim:1",
            "claim_type": "bounded_predictive_relationship",
            "scope": {"sample": "confirmation"},
            "evidence_state": "unknown",
            "evidence_refs": [],
        }],
        "obligations": [{
            "schema_version": 1,
            "obligation_id": "obligation-1",
            "contract_hash": "1" * 64,
            "claim_ids": ["claim-1"],
            "obligation_kind": "preregistered_test",
            "title_zh": "预注册检验",
            "epistemic_question": "Can the claim survive its test?",
            "scope": {"sample": "confirmation"},
            "discharge_criterion": {"rule_ref": "trial-plan:1#reject"},
            "status": "open",
            "materiality": "decision_blocking",
            "methodology_hash": "3" * 64,
            "created_event_ref": "trace:init",
        }],
        "pending_adjudications": [],
        "pending_closure": None,
    })


def _closure_proposal(
    checkpoint: dict,
    *,
    proposal_id: str,
    candidate_trial_frontier: list[dict] | None = None,
) -> dict:
    return validate_search_exhaustion_proposal({
        "schema_version": 1,
        "proposal_id": proposal_id,
        "contract_hash": checkpoint["contract_hash"],
        "claim_projection_hash": json_hash(checkpoint["claims"]),
        "obligation_projection_hash": json_hash(
            checkpoint["obligations"]
        ),
        "graph_hash": "4" * 64,
        "methodology_hash": checkpoint["methodology_hash"],
        "coverage_summary": {
            "attempted_regions": 1,
            "declared_scope_assessed": True,
            "stopping_rules_assessed": True,
            "frontier_assessed": True,
        },
        "blocking_obligations": ["obligation-1"],
        "remaining_unknowns": [{
            "claim_id": "claim-1",
            "reason": "required evidence is unavailable",
        }],
        "attempted_trial_refs": ["trial:1"],
        "candidate_trial_frontier": candidate_trial_frontier or [],
        "frontier_exclusions": [],
        "discovery_lens_refs": ["methodology:first-principles"],
        "reentry_predicates": [{
            "field": "data_availability_hash",
            "changes_from": "unavailable",
        }],
        "disposition": "blocked",
        "closure_challenge_required": True,
    })


def _decision(
    proposal: dict,
    *,
    disposition: str,
    challenge_findings: list[dict] | None = None,
) -> dict:
    return validate_search_exhaustion_decision({
        "schema_version": 1,
        "decision_id": f"decision-{disposition}",
        "proposal_hash": proposal["proposal_hash"],
        "disposition": disposition,
        "authority_class": "independent_reviewer",
        "authority_ref": "review:closure-challenge",
        "methodology_hash": proposal["methodology_hash"],
        "challenge_findings": challenge_findings or [],
    })


def test_blocked_closure_preserves_unknown_claim_and_open_obligation() -> None:
    checkpoint = _open_checkpoint()
    proposal = _closure_proposal(
        checkpoint,
        proposal_id="closure-blocked",
    )

    closed = replay_research_cycle_events(
        checkpoint,
        events=[
            {"event_type": "closure_proposed", "proposal": proposal},
            {
                "event_type": "closure_decided",
                "decision": _decision(proposal, disposition="accepted"),
            },
        ],
        expected_base_hash=checkpoint["projection_hash"],
    )

    assert closed["closure"]["disposition"] == "blocked"
    assert closed["closure"]["reentry_predicates"] == [{
        "field": "data_availability_hash",
        "changes_from": "unavailable",
    }]
    assert closed["claims"][0]["evidence_state"] == "unknown"
    assert closed["obligations"][0]["status"] == "open"


def test_challenger_rejects_closure_with_seeded_frontier_omission() -> None:
    checkpoint = _open_checkpoint()
    before_claims = deepcopy(checkpoint["claims"])
    before_obligations = deepcopy(checkpoint["obligations"])
    proposal = _closure_proposal(
        checkpoint,
        proposal_id="closure-with-seeded-omission",
    )

    reviewed = replay_research_cycle_events(
        checkpoint,
        events=[
            {"event_type": "closure_proposed", "proposal": proposal},
            {
                "event_type": "closure_decided",
                "decision": _decision(
                    proposal,
                    disposition="revision_requested",
                    challenge_findings=[{
                        "finding": "actionable frontier candidate omitted",
                        "omitted_ref": "trial:liquidity-regime-contrast",
                        "required_action": "assess candidate before closure",
                    }],
                ),
            },
        ],
        expected_base_hash=checkpoint["projection_hash"],
    )

    assert reviewed["closure"] is None
    assert reviewed["pending_closure"] is None
    assert reviewed["claims"] == before_claims
    assert reviewed["obligations"] == before_obligations
