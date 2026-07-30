"""A material reopened question invalidates bounded closure atomically."""

from __future__ import annotations

from copy import deepcopy

from server.services.research_graph.protocol import json_hash
from server.services.research_graph.research_cycle.adjudication import (
    validate_adjudication_decision,
    validate_adjudication_proposal,
)
from server.services.research_graph.research_cycle.closure import (
    validate_search_exhaustion_proposal,
)
from server.services.research_graph.research_cycle.replay import (
    replay_research_cycle_events,
    validate_research_cycle_checkpoint,
)


def _closed_checkpoint(*, pending: bool = False) -> dict:
    base = validate_research_cycle_checkpoint({
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
            "scope": {"product_group": "CNFutures"},
            "evidence_state": "inconclusive",
            "evidence_refs": ["evidence:old-trial"],
        }],
        "obligations": [{
            "schema_version": 1,
            "obligation_id": "obligation-1",
            "contract_hash": "1" * 64,
            "claim_ids": ["claim-1"],
            "obligation_kind": "bounded_test",
            "title_zh": "有界检验信息性",
            "epistemic_question": "Was the bounded test informative?",
            "scope": {"product_group": "CNFutures"},
            "discharge_criterion": {"rule_ref": "trial:bounded"},
            "status": "discharged",
            "materiality": "decision_blocking",
            "methodology_hash": "3" * 64,
            "created_event_ref": "trace:init",
        }],
        "pending_adjudications": [],
        "pending_closure": None,
    })
    closure = validate_search_exhaustion_proposal({
        "schema_version": 1,
        "proposal_id": "closure-1",
        "contract_hash": base["contract_hash"],
        "claim_projection_hash": json_hash(base["claims"]),
        "obligation_projection_hash": json_hash(base["obligations"]),
        "graph_hash": "4" * 64,
        "methodology_hash": base["methodology_hash"],
        "coverage_summary": {
            "attempted_regions": 1,
            "declared_scope_assessed": True,
            "stopping_rules_assessed": True,
            "frontier_assessed": True,
        },
        "blocking_obligations": [],
        "remaining_unknowns": [],
        "attempted_trial_refs": ["trial:old"],
        "candidate_trial_frontier": [],
        "frontier_exclusions": [],
        "discovery_lens_refs": ["methodology:first-principles"],
        "reentry_predicates": [{"field": "methodology_hash"}],
        "disposition": "exhausted_without_support",
        "closure_challenge_required": True,
    })
    value = {
        key: deepcopy(item)
        for key, item in base.items()
        if key != "projection_hash"
    }
    value["pending_closure" if pending else "closure"] = closure
    return validate_research_cycle_checkpoint(value)


def _proposal(
    checkpoint: dict,
    *,
    materiality: str = "decision_blocking",
    reopen_existing: bool = False,
) -> dict:
    obligation_delta = (
        [{
            "obligation_id": "obligation-1",
            "from_state": "discharged",
            "to_state": "reopened",
            "criterion_ref": "methodology:new-test",
        }]
        if reopen_existing
        else [{
            "obligation_id": "obligation-new",
            "from_state": "absent",
            "to_state": "open",
            "criterion_ref": "methodology:new-test",
            "obligation": {
                "schema_version": 1,
                "obligation_id": "obligation-new",
                "contract_hash": checkpoint["contract_hash"],
                "claim_ids": ["claim-1"],
                "obligation_kind": "methodology_reentry",
                "title_zh": "方法变化影响",
                "epistemic_question": "Does the new method change the result?",
                "scope": {"product_group": "CNFutures"},
                "discharge_criterion": {"rule_ref": "methodology:new-test"},
                "status": "open",
                "materiality": materiality,
                "methodology_hash": checkpoint["methodology_hash"],
                "created_event_ref": "evidence:new-methodology",
            },
        }]
    )
    return validate_adjudication_proposal({
        "schema_version": 1,
        "proposal_id": f"proposal-reopen-{materiality}",
        "contract_hash": checkpoint["contract_hash"],
        "trial_plan_hash": checkpoint["trial_plan_hash"],
        "methodology_hash": checkpoint["methodology_hash"],
        "evidence_refs": ["evidence:new-methodology"],
        "claim_evidence_delta": [],
        "claim_delta_noop_reason": "new question is not Claim evidence",
        "obligation_delta": obligation_delta,
        "decision_warrant": {
            "finding_refs": ["evidence:new-methodology"],
            "rule_refs": ["methodology:impact"],
            "inference_type": "semantic",
            "preregistered": False,
            "alternative_refs": [],
            "limitation_refs": [],
            "reentry_predicates": [{"field": "methodology_hash"}],
            "required_authority": "independent_reviewer",
        },
    })


def _replay(
    checkpoint: dict,
    *,
    materiality: str = "decision_blocking",
    disposition: str = "accepted",
    reopen_existing: bool = False,
) -> dict:
    proposal = _proposal(
        checkpoint,
        materiality=materiality,
        reopen_existing=reopen_existing,
    )
    decision = validate_adjudication_decision({
        "schema_version": 1,
        "decision_id": f"decision-{materiality}-{disposition}",
        "proposal_hash": proposal["proposal_hash"],
        "disposition": disposition,
        "authority_class": "independent_reviewer",
        "authority_ref": "review:methodology-impact",
        "methodology_hash": checkpoint["methodology_hash"],
    })
    return replay_research_cycle_events(
        checkpoint,
        events=[
            {"event_type": "adjudication_proposed", "proposal": proposal},
            {"event_type": "adjudication_decided", "decision": decision},
        ],
        expected_base_hash=checkpoint["projection_hash"],
    )


def test_accepted_new_blocking_obligation_invalidates_accepted_closure(
) -> None:
    before = _closed_checkpoint()
    after = _replay(before)

    assert before["closure"] is not None
    assert after["closure"] is None
    assert after["pending_closure"] is None
    assert after["obligations"][-1]["status"] == "open"


def test_accepted_new_blocking_obligation_invalidates_pending_closure(
) -> None:
    after = _replay(_closed_checkpoint(pending=True))

    assert after["pending_closure"] is None
    assert after["closure"] is None


def test_accepted_reopened_blocking_obligation_invalidates_closure() -> None:
    after = _replay(_closed_checkpoint(), reopen_existing=True)

    assert after["closure"] is None
    assert after["obligations"][0]["status"] == "reopened"


def test_rejected_or_nonblocking_delta_preserves_closure() -> None:
    before = _closed_checkpoint()

    rejected = _replay(before, disposition="rejected")
    nonblocking = _replay(before, materiality="non_blocking")

    assert rejected["closure"] == before["closure"]
    assert nonblocking["closure"] == before["closure"]
