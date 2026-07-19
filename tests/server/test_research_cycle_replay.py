from __future__ import annotations

from copy import deepcopy

import pytest

from server.services.research_graph.research_cycle.adjudication import (
    validate_adjudication_decision,
    validate_adjudication_proposal,
)
from server.services.research_graph.research_cycle.replay import (
    replay_research_cycle_events,
    validate_research_cycle_checkpoint,
)
from server.services.research_graph.research_cycle.closure import (
    validate_search_exhaustion_decision,
    validate_search_exhaustion_proposal,
)
from server.services.research_graph.protocol import json_hash


def _checkpoint() -> dict:
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
            "scope": {"sample": "confirmatory"},
            "evidence_state": "unknown",
            "evidence_refs": [],
        }],
        "obligations": [{
            "schema_version": 1,
            "obligation_id": "obligation-1",
            "contract_hash": "1" * 64,
            "claim_ids": ["claim-1"],
            "obligation_kind": "preregistered_test",
            "epistemic_question": "Does the preregistered test reject?",
            "scope": {"sample": "confirmatory"},
            "discharge_criterion": {"rule_ref": "trial-plan:1#reject"},
            "status": "open",
            "materiality": "decision_blocking",
            "methodology_hash": "3" * 64,
            "created_event_ref": "trace:init",
        }],
        "pending_adjudications": [],
        "pending_closure": None,
    })


def _proposal() -> dict:
    return validate_adjudication_proposal({
        "schema_version": 1,
        "proposal_id": "proposal-1",
        "contract_hash": "1" * 64,
        "trial_plan_hash": "2" * 64,
        "methodology_hash": "3" * 64,
        "evidence_refs": ["evidence:failed-test"],
        "claim_evidence_delta": [{
            "claim_id": "claim-1",
            "from_state": "unknown",
            "to_state": "contradicted",
            "evidence_grade": "preregistered",
            "scope": {"sample": "confirmatory"},
        }],
        "obligation_delta": [{
            "obligation_id": "obligation-1",
            "from_state": "open",
            "to_state": "discharged",
            "criterion_ref": "trial-plan:1#reject",
        }],
        "decision_warrant": {
            "finding_refs": ["evidence:failed-test"],
            "rule_refs": ["trial-plan:1#reject"],
            "inference_type": "preregistered",
            "preregistered": True,
            "alternative_refs": [],
            "limitation_refs": [],
            "reentry_predicates": [],
            "required_authority": "preregistered_rule",
        },
    })


def _decision(proposal_hash: str, *, disposition: str = "accepted") -> dict:
    return validate_adjudication_decision({
        "schema_version": 1,
        "decision_id": "decision-1",
        "proposal_hash": proposal_hash,
        "disposition": disposition,
        "authority_class": "preregistered_rule",
        "authority_ref": "trial-plan:1#reject",
        "methodology_hash": "3" * 64,
    })


def test_accepted_pair_replays_atomically_into_one_checkpoint() -> None:
    before = _checkpoint()
    proposal = _proposal()
    after = replay_research_cycle_events(
        before,
        events=[
            {
                "event_type": "adjudication_proposed",
                "proposal": proposal,
            },
            {
                "event_type": "adjudication_decided",
                "decision": _decision(proposal["proposal_hash"]),
            },
        ],
        expected_base_hash=before["projection_hash"],
    )

    assert before["claims"][0]["evidence_state"] == "unknown"
    assert after["claims"][0]["evidence_state"] == "contradicted"
    assert after["claims"][0]["evidence_refs"] == ["evidence:failed-test"]
    assert after["obligations"][0]["status"] == "discharged"
    assert after["pending_adjudications"] == []
    assert after["projection_hash"] != before["projection_hash"]


def test_pending_or_rejected_adjudication_changes_no_accepted_state() -> None:
    before = _checkpoint()
    proposal = _proposal()
    pending = replay_research_cycle_events(
        before,
        events=[{
            "event_type": "adjudication_proposed",
            "proposal": proposal,
        }],
        expected_base_hash=before["projection_hash"],
    )
    rejected = replay_research_cycle_events(
        pending,
        events=[{
            "event_type": "adjudication_decided",
            "decision": _decision(
                proposal["proposal_hash"],
                disposition="rejected",
            ),
        }],
        expected_base_hash=pending["projection_hash"],
    )

    assert pending["claims"] == before["claims"]
    assert pending["obligations"] == before["obligations"]
    assert len(pending["pending_adjudications"]) == 1
    assert rejected["claims"] == before["claims"]
    assert rejected["obligations"] == before["obligations"]
    assert rejected["pending_adjudications"] == []


def test_stale_or_invalid_pair_leaves_input_checkpoint_unchanged() -> None:
    before = _checkpoint()
    snapshot = deepcopy(before)
    proposal = _proposal()

    with pytest.raises(ValueError, match="base projection hash is stale"):
        replay_research_cycle_events(
            before,
            events=[],
            expected_base_hash="9" * 64,
        )

    wrong = _decision(proposal["proposal_hash"])
    wrong["authority_class"] = "deterministic_verifier"
    with pytest.raises(ValueError, match="authority does not satisfy"):
        replay_research_cycle_events(
            before,
            events=[
                {
                    "event_type": "adjudication_proposed",
                    "proposal": proposal,
                },
                {
                    "event_type": "adjudication_decided",
                    "decision": wrong,
                },
            ],
            expected_base_hash=before["projection_hash"],
        )

    assert before == snapshot


def test_bounded_closure_requires_current_projection_and_challenge() -> None:
    before = _checkpoint()
    proposal = _proposal()
    adjudicated = replay_research_cycle_events(
        before,
        events=[
            {
                "event_type": "adjudication_proposed",
                "proposal": proposal,
            },
            {
                "event_type": "adjudication_decided",
                "decision": _decision(proposal["proposal_hash"]),
            },
        ],
        expected_base_hash=before["projection_hash"],
    )
    closure = validate_search_exhaustion_proposal({
        "schema_version": 1,
        "proposal_id": "closure-1",
        "contract_hash": adjudicated["contract_hash"],
        "claim_projection_hash": json_hash(adjudicated["claims"]),
        "obligation_projection_hash": json_hash(
            adjudicated["obligations"]
        ),
        "graph_hash": "4" * 64,
        "methodology_hash": adjudicated["methodology_hash"],
        "coverage_summary": {"attempted_regions": 1},
        "blocking_obligations": [],
        "remaining_unknowns": [],
        "attempted_trial_refs": ["trial:1"],
        "candidate_trial_frontier": [],
        "frontier_exclusions": [],
        "discovery_lens_refs": ["methodology:first-principles"],
        "reentry_predicates": [{"field": "methodology_hash"}],
        "disposition": "decision_ready",
        "closure_challenge_required": True,
    })
    decision = validate_search_exhaustion_decision({
        "schema_version": 1,
        "decision_id": "closure-decision-1",
        "proposal_hash": closure["proposal_hash"],
        "disposition": "accepted",
        "authority_class": "independent_reviewer",
        "authority_ref": "review:closure-1",
        "methodology_hash": adjudicated["methodology_hash"],
    })
    closed = replay_research_cycle_events(
        adjudicated,
        events=[
            {"event_type": "closure_proposed", "proposal": closure},
            {"event_type": "closure_decided", "decision": decision},
        ],
        expected_base_hash=adjudicated["projection_hash"],
    )

    assert closed["pending_closure"] is None
    assert closed["closure"]["disposition"] == "decision_ready"

    stale = {
        **{
            key: value
            for key, value in closure.items()
            if key != "proposal_hash"
        },
        "claim_projection_hash": "9" * 64,
    }
    with pytest.raises(
        ValueError,
        match="Claim projection is stale",
    ):
        replay_research_cycle_events(
            adjudicated,
            events=[{
                "event_type": "closure_proposed",
                "proposal": stale,
            }],
            expected_base_hash=adjudicated["projection_hash"],
        )


def test_accepted_semantic_discovery_can_add_a_new_obligation() -> None:
    before = _checkpoint()
    proposal = validate_adjudication_proposal({
        "schema_version": 1,
        "proposal_id": "proposal-discovery",
        "contract_hash": before["contract_hash"],
        "trial_plan_hash": before["trial_plan_hash"],
        "methodology_hash": before["methodology_hash"],
        "evidence_refs": ["trace:first-principles-review"],
        "claim_evidence_delta": [],
        "claim_delta_noop_reason": "new question is not empirical support",
        "obligation_delta": [{
            "obligation_id": "obligation-discovered",
            "from_state": "absent",
            "to_state": "open",
            "criterion_ref": "methodology:delivery-window-test",
            "obligation": {
                "schema_version": 1,
                "obligation_id": "obligation-discovered",
                "contract_hash": before["contract_hash"],
                "claim_ids": ["claim-1"],
                "obligation_kind": "delivery_window_discontinuity",
                "epistemic_question": "Is delivery proximity the mechanism?",
                "scope": {"delivery_window_days": 10},
                "discharge_criterion": {
                    "method": "predeclared window perturbation"
                },
                "status": "open",
                "materiality": "decision_blocking",
                "methodology_hash": before["methodology_hash"],
                "created_event_ref": "trace:first-principles-review",
            },
        }],
        "decision_warrant": {
            "finding_refs": ["trace:first-principles-review"],
            "rule_refs": ["methodology:obligation-discovery"],
            "inference_type": "semantic",
            "preregistered": False,
            "alternative_refs": [],
            "limitation_refs": [],
            "reentry_predicates": [],
            "required_authority": "independent_reviewer",
        },
    })
    decision = validate_adjudication_decision({
        "schema_version": 1,
        "decision_id": "decision-discovery",
        "proposal_hash": proposal["proposal_hash"],
        "disposition": "accepted",
        "authority_class": "independent_reviewer",
        "authority_ref": "review:discovery",
        "methodology_hash": before["methodology_hash"],
    })
    after = replay_research_cycle_events(
        before,
        events=[
            {"event_type": "adjudication_proposed", "proposal": proposal},
            {"event_type": "adjudication_decided", "decision": decision},
        ],
        expected_base_hash=before["projection_hash"],
    )

    assert after["claims"] == before["claims"]
    assert after["obligations"][-1]["obligation_id"] == (
        "obligation-discovered"
    )
