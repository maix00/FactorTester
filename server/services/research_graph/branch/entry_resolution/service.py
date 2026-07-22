"""Two-stage Entry Resolution lifecycle behind one small interface."""

from __future__ import annotations

from typing import Any

from .assessments import validate_entry_requirement_assessments
from .receipts import (
    project_node_entry_resolution,
    record_assessment_receipts,
)
from .frame import (
    active_entry_requirement_ids,
    advance_entry_resolution_frame,
    entry_resolution_trace_delta,
)
from ..entry_requirements import requirement_map


def assess_departure(
    *, graph: dict[str, Any], node: dict[str, Any],
    checkpoint: dict[str, Any] | None, current_frame: dict[str, Any],
    current_node: str, target_node: str, submitted: Any,
) -> dict[str, Any]:
    """Validate only unresolved entry work and retain any bounded detour."""
    assessments = validate_entry_requirement_assessments(
        graph=graph,
        node=node,
        checkpoint=checkpoint,
        target_node=target_node,
        submitted=submitted,
        required_requirement_ids=active_entry_requirement_ids(
            frame=current_frame,
            current_node=current_node,
        ),
    )
    return {
        "current_frame": current_frame,
        "current_node": current_node,
        "target_node": target_node,
        "assessments": assessments,
        "departure_frame": advance_entry_resolution_frame(
            frame=current_frame,
            current_node=current_node,
            target_node=target_node,
            assessments=assessments,
        ),
    }


def project_arrival(
    *, attempt: dict[str, Any], graph: dict[str, Any],
    checkpoint: dict[str, Any] | None, scope: dict[str, str],
    trace_ref: str,
) -> dict[str, Any]:
    """Bind accepted receipts, project the target entry, and emit its delta."""
    assessments = attempt["assessments"]
    receipt_frame = record_assessment_receipts(
        previous_frame=attempt["departure_frame"],
        graph=graph,
        checkpoint=checkpoint,
        scope=scope,
        entry_node=attempt["current_node"],
        accepted_assessments=assessments,
        assessment_trace_ref=trace_ref,
    )
    if receipt_frame.get("status") == "pending":
        frame = receipt_frame
    else:
        frame = project_node_entry_resolution(
            previous_frame=receipt_frame,
            graph=graph,
            target_node=attempt["target_node"],
            checkpoint=checkpoint,
            scope=scope,
        )
    return {
        "assessments": assessments,
        "frame": frame,
        "trace_delta": entry_resolution_trace_delta(
            current_frame=attempt["current_frame"],
            projected_frame=frame,
            current_node=attempt["current_node"],
            target_node=attempt["target_node"],
            assessments=assessments,
            requirement_titles={
                requirement_id: str(item.get("title_zh") or requirement_id)
                for requirement_id, item in requirement_map(graph).items()
            },
        ),
    }
