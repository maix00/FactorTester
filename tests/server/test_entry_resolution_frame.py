"""Graph reentry resolves only changed requirement contracts."""

from server.services.research_graph.branch.entry_resolution_frame import (
    active_entry_requirement_ids,
    advance_entry_resolution_frame,
    initial_entry_resolution_frame,
)
from server.services.research_graph.branch.entry_assessment_receipts import (
    project_node_entry_resolution,
    record_assessment_receipts,
)


def test_reentry_frame_keeps_only_unresolved_requirement_changes() -> None:
    descriptor = {
        "continuation_mode": "same_node_reentry",
        "source_graph_version": 8,
        "target_graph_version": 9,
        "target_node": "factor_semantics",
        "requirement_preflight": {
            "delta_hash": "a" * 64,
            "assessment_required_ids": ["factor_semantics.expression_identity"],
            "entry_removed_ids": ["factor_semantics.legacy_prompt"],
            "entry_metadata_changed_ids": [],
        },
    }

    frame = initial_entry_resolution_frame(descriptor)

    assert frame["status"] == "pending"
    assert frame["resume_node"] == "factor_semantics"
    assert frame["unresolved_requirement_ids"] == [
        "factor_semantics.expression_identity"
    ]
    resolved = advance_entry_resolution_frame(
        frame=frame,
        current_node="factor_semantics",
        target_node="validation_design",
        assessments=[{
            "requirement_id": "factor_semantics.expression_identity",
            "entry_effect": {"status": "pass"},
        }],
    )
    assert resolved["status"] == "resolved"
    assert resolved["unresolved_requirement_ids"] == []
    assert active_entry_requirement_ids(
        frame=resolved,
        current_node="factor_semantics",
    ) == []


def test_exact_receipt_avoids_repeating_an_unchanged_requirement() -> None:
    requirement_id = "data.required_fields"
    graph = {
        "nodes": [
            {"node_id": "a", "entry_requirement_refs": [requirement_id]},
            {"node_id": "b", "entry_requirement_refs": [requirement_id]},
        ],
        "requirement_catalog": {"requirements": [{
            "requirement_id": requirement_id,
            "revision": 1,
        }]},
    }
    obligation = {
        "obligation_id": "data-1",
        "status": "open",
        "requirement_refs": [requirement_id],
        "scope": {"product": "A.DCE"},
    }
    checkpoint = {
        "contract_hash": "b" * 64,
        "methodology_hash": "c" * 64,
        "obligations": [obligation],
    }
    assessment = {
        "requirement_id": requirement_id,
        "requirement_revision": 1,
        "applicability": {
            "status": "applicable",
            "fact_refs": ["scope:A.DCE"],
        },
        "coverage": {
            "decision": "map_existing",
            "obligation_refs": ["obligation:data-1"],
        },
        "resolution": {
            "route": "cli_evidence",
            "reuse_status": "none",
            "validation_refs": ["data-check:1"],
        },
        "entry_effect": {"status": "pass", "limitation_refs": []},
    }
    scope = {"product_group": "CNFutures", "workspace_id": "workspace-1"}

    receipts = record_assessment_receipts(
        previous_frame={},
        graph=graph,
        checkpoint=checkpoint,
        scope=scope,
        entry_node="a",
        accepted_assessments=[assessment],
        assessment_trace_ref="trace:1",
    )
    first_b_entry = project_node_entry_resolution(
        previous_frame=receipts,
        graph=graph,
        target_node="b",
        checkpoint=checkpoint,
        scope=scope,
    )
    assert first_b_entry["unresolved_requirement_ids"] == [requirement_id]
    frame = project_node_entry_resolution(
        previous_frame=receipts,
        graph=graph,
        target_node="a",
        checkpoint=checkpoint,
        scope=scope,
    )
    assert frame["status"] == "resolved"
    assert frame["reused_requirement_ids"] == [requirement_id]
    changed_checkpoint = {**checkpoint, "obligations": [{
        **obligation,
        "status": "reopened",
    }]}
    reopened = project_node_entry_resolution(
        previous_frame=frame,
        graph=graph,
        target_node="a",
        checkpoint=changed_checkpoint,
        scope=scope,
    )
    assert reopened["unresolved_requirement_ids"] == [requirement_id]
    assert reopened["reference_only_requirement_ids"] == [requirement_id]
