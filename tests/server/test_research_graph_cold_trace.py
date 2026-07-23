from __future__ import annotations

from server.services.research_graph.branch.trace_compaction import (
    compact_entry_assessment_receipts,
    compact_entry_resolution_delta,
    compact_research_cycle_event_receipts,
)
from server.services.research_graph.research_cycle.replay import (
    replay_research_cycle_events,
    validate_research_cycle_checkpoint,
)
from server.services.research_graph.research_cycle.trace_replay import (
    verify_research_cycle_trace,
)
from server.services.research_graph.report_checkpoint import (
    research_cycle_deltas,
)


def test_entry_assessment_receipts_keep_decisions_without_long_body() -> None:
    assessments = [{
        "requirement_id": "factor_semantics.expression_identity",
        "requirement_revision": 3,
        "gate_policy": "resolve_before_exit",
        "applicability": {
            "status": "applicable",
            "reason_zh": "很长的解释正文" * 100,
            "fact_refs": ["factor-expression:sha256:" + "a" * 64],
        },
        "coverage": {
            "decision": "map_existing",
            "obligation_refs": ["obligation:semantics"],
        },
        "resolution": {
            "route": "existing_evidence",
            "reuse_status": "partial",
            "validation_refs": ["evidence:semantics"],
        },
        "entry_effect": {
            "status": "pass_limited",
            "limitation_refs": ["limitation:direction"],
        },
    }]

    receipts = compact_entry_assessment_receipts(assessments)

    assert receipts == [{
        "requirement_id": "factor_semantics.expression_identity",
        "requirement_revision": 3,
        "assessment_hash": receipts[0]["assessment_hash"],
        "applicability_status": "applicable",
        "coverage_decision": "map_existing",
        "entry_effect_status": "pass_limited",
        "obligation_refs": ["obligation:semantics"],
        "limitation_refs": ["limitation:direction"],
    }]
    assert len(receipts[0]["assessment_hash"]) == 64
    assert "reason_zh" not in receipts[0]
    assert "validation_refs" not in receipts[0]


def test_cycle_event_receipts_preserve_auditable_delta_identity() -> None:
    proposal = {
        "schema_version": 2,
        "proposal_id": "proposal-1",
        "proposal_hash": "a" * 64,
        "claim_evidence_delta": [{
            "claim_id": "claim-1",
            "from_state": "unknown",
            "to_state": "supported",
        }],
        "obligation_delta": [{
            "obligation_id": "obligation-1",
            "from_state": "open",
            "to_state": "discharged",
        }],
        "recommended_action": "advance_trial_stage",
    }
    decision = {
        "decision_id": "decision-1",
        "proposal_hash": "a" * 64,
        "disposition": "accepted",
        "authority_class": "independent_reviewer",
    }

    receipts = compact_research_cycle_event_receipts([
        {"event_type": "adjudication_proposed", "proposal": proposal},
        {"event_type": "adjudication_decided", "decision": decision},
    ])

    assert receipts == [{
        "event_type": "adjudication_proposed",
        "proposal_id": "proposal-1",
        "proposal_hash": "a" * 64,
        "recommended_action": "advance_trial_stage",
        "claim_deltas": [{
            "claim_id": "claim-1",
            "from_state": "unknown",
            "to_state": "supported",
        }],
        "obligation_deltas": [{
            "obligation_id": "obligation-1",
            "from_state": "open",
            "to_state": "discharged",
        }],
    }, {
        "event_type": "adjudication_decided",
        "decision_id": "decision-1",
        "proposal_hash": "a" * 64,
        "disposition": "accepted",
        "authority_class": "independent_reviewer",
    }]


def test_entry_resolution_delta_drops_repeated_titles_only() -> None:
    delta = {
        "schema_version": 1,
        "reason": "graph_continuation",
        "assessed_requirement_ids": ["factor_semantics.expression_identity"],
        "reused_requirement_ids": [],
        "reference_only_requirement_ids": [],
        "unresolved_requirement_ids": [],
        "items": [{
            "requirement_id": "factor_semantics.expression_identity",
            "title_zh": "重复的完整要求标题",
            "assessed": True,
            "change_kind": "revised",
            "resolution_status": "assessed_pass",
        }],
        "resume_node": "factor_semantics",
    }

    compact = compact_entry_resolution_delta(delta)

    assert compact["items"] == [{
        "requirement_id": "factor_semantics.expression_identity",
        "change_kind": "revised",
        "resolution_status": "assessed_pass",
    }]
    assert "title_zh" not in compact["items"][0]
    assert "assessed" not in compact["items"][0]


def test_trace_replay_accepts_hash_verified_cold_events() -> None:
    checkpoint = validate_research_cycle_checkpoint({
        "schema_version": 1,
        "contract_hash": "1" * 64,
        "trial_plan_hash": "",
        "methodology_hash": "3" * 64,
        "claims": [],
        "obligations": [],
        "pending_adjudications": [],
        "pending_closure": None,
    })
    events = [{
        "event_type": "trial_plan_bound",
        "from_hash": "",
        "to_hash": "2" * 64,
    }]
    projected = replay_research_cycle_events(
        checkpoint,
        events=events,
        expected_base_hash=checkpoint["projection_hash"],
    )
    event = {
        "schema_version": 1,
        "parent_trace_ref": "trace:previous",
        "checkpoint_before_hash": checkpoint["projection_hash"],
        "events_ref": "research-graph-object:sha256:" + "a" * 64,
        "event_receipts": compact_research_cycle_event_receipts(events),
    }

    replayed = verify_research_cycle_trace(
        previous_checkpoint=checkpoint,
        previous_trace_id="previous",
        event=event,
        projected_checkpoint=projected,
        resolved_events=events,
    )

    assert replayed["projection_hash"] == projected["projection_hash"]


def test_report_delta_projection_reads_compact_event_receipts() -> None:
    evidence = {
        "research_cycle": {
            "schema_version": 1,
            "events_ref": "research-graph-object:sha256:" + "a" * 64,
            "event_receipts": [{
                "event_type": "adjudication_proposed",
                "proposal_id": "proposal-1",
                "proposal_hash": "b" * 64,
                "claim_deltas": [{
                    "claim_id": "claim-1",
                    "from_state": "unknown",
                    "to_state": "supported",
                }],
                "obligation_deltas": [{
                    "obligation_id": "obligation-1",
                    "from_state": "open",
                    "to_state": "discharged",
                }],
            }],
        },
    }

    obligations, claims = research_cycle_deltas(evidence)

    assert obligations == [{
        "obligation_id": "obligation-1",
        "from_state": "open",
        "to_state": "discharged",
    }]
    assert claims == [{
        "claim_id": "claim-1",
        "from_state": "unknown",
        "to_state": "supported",
    }]


def test_compact_receipt_keeps_obligation_requirement_reclassification(
) -> None:
    events = [{
        "event_type": "adjudication_proposed",
        "proposal": {
            "proposal_id": "proposal-reclassify",
            "proposal_hash": "b" * 64,
            "recommended_action": "continue_execution",
            "claim_evidence_delta": [],
            "obligation_delta": [{
                "obligation_id": "obligation-1",
                "from_state": "open",
                "to_state": "open",
                "from_requirement_refs": ["other.unclassified"],
                "to_requirement_refs": ["data.required-fields"],
            }],
        },
    }]

    receipts = compact_research_cycle_event_receipts(events)
    obligations, _ = research_cycle_deltas({
        "research_cycle": {"event_receipts": receipts},
    })

    assert obligations == [{
        "obligation_id": "obligation-1",
        "from_state": "open",
        "to_state": "open",
        "from_requirement_refs": ["other.unclassified"],
        "to_requirement_refs": ["data.required-fields"],
    }]
