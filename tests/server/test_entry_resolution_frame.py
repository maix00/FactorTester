"""Graph reentry resolves only changed requirement contracts."""

from server.services.research_graph.branch.entry_resolution_frame import (
    advance_entry_resolution_frame,
    initial_entry_resolution_frame,
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
