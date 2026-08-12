from server.services.research_graph.research_cycle.checkpoint_deltas import (
    accepted_checkpoint_deltas,
)


def test_checkpoint_deltas_report_only_applied_state_changes() -> None:
    before = {
        "claims": [{
            "claim_id": "claim-1",
            "evidence_state": "unknown",
        }],
        "obligations": [{
            "obligation_id": "obligation-1",
            "status": "open",
            "requirement_refs": ["other.unclassified"],
        }],
    }
    after = {
        "claims": [{
            "claim_id": "claim-1",
            "evidence_state": "supported",
        }],
        "obligations": [{
            "obligation_id": "obligation-1",
            "status": "open",
            "requirement_refs": ["data.required-fields"],
        }, {
            "obligation_id": "obligation-2",
            "status": "open",
        }],
    }

    assert accepted_checkpoint_deltas(before, after) == {
        "obligation_deltas": [{
            "obligation_id": "obligation-1",
            "from_state": "open",
            "to_state": "open",
            "from_requirement_refs": ["other.unclassified"],
            "to_requirement_refs": ["data.required-fields"],
        }, {
            "obligation_id": "obligation-2",
            "from_state": "absent",
            "to_state": "open",
        }],
        "claim_deltas": [{
            "claim_id": "claim-1",
            "from_state": "unknown",
            "to_state": "supported",
        }],
    }


def test_checkpoint_deltas_ignore_pending_or_rejected_noops() -> None:
    checkpoint = {
        "claims": [{
            "claim_id": "claim-1",
            "evidence_state": "unknown",
        }],
        "obligations": [{
            "obligation_id": "obligation-1",
            "status": "open",
        }],
    }

    assert accepted_checkpoint_deltas(checkpoint, checkpoint) == {
        "obligation_deltas": [],
        "claim_deltas": [],
    }
