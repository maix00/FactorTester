"""Two-stage Entry Resolution lifecycle behind one small interface."""

from __future__ import annotations

from typing import Any

from .arrival import project_arrival_state
from .assessments import validate_entry_requirement_assessments
from .events import entry_resolution_event_envelope
from .receipts import record_assessment_receipts
from .stack_routing import advance_active_frame
from .stack_state import canonical_entry_resolution_state
from .trace_delta import entry_resolution_trace_delta
from .view import active_entry_requirement_ids
from ..entry_requirements import requirement_map


def assess_departure(
    *,
    graph: dict[str, Any],
    node: dict[str, Any],
    checkpoint: dict[str, Any] | None,
    current_frame: dict[str, Any],
    current_node: str,
    target_node: str,
    submitted: Any,
    scope: dict[str, str],
    trace_ref: str,
) -> dict[str, Any]:
    """Create/reuse this node's attempt, validate it, then route."""
    before = canonical_entry_resolution_state(current_frame)
    attempt_state = project_arrival_state(
        previous_state=before,
        graph=graph,
        target_node=current_node,
        checkpoint=checkpoint,
        scope=scope,
        origin_ref=f"{trace_ref}:departure",
        current_node=current_node,
        retain_target_frame=True,
    )
    assessments = validate_entry_requirement_assessments(
        graph=graph,
        node=node,
        checkpoint=checkpoint,
        target_node=target_node,
        submitted=submitted,
        required_requirement_ids=active_entry_requirement_ids(
            frame=attempt_state,
            current_node=current_node,
        ),
    )
    return {
        "current_frame": before,
        "attempt_frame": attempt_state,
        "current_node": current_node,
        "target_node": target_node,
        "assessments": assessments,
        "departure_frame": advance_active_frame(
            state=attempt_state,
            current_node=current_node,
            target_node=target_node,
            assessments=assessments,
        ),
    }


def project_arrival(
    *,
    attempt: dict[str, Any],
    graph: dict[str, Any],
    checkpoint: dict[str, Any] | None,
    scope: dict[str, str],
    trace_ref: str,
) -> dict[str, Any]:
    """Bind receipts, project target entry, and emit separate audit objects."""
    assessments = attempt["assessments"]
    receipt_state = record_assessment_receipts(
        previous_frame=attempt["departure_frame"],
        graph=graph,
        checkpoint=checkpoint,
        scope=scope,
        entry_node=attempt["current_node"],
        accepted_assessments=assessments,
        assessment_trace_ref=trace_ref,
    )
    frame = project_arrival_state(
        previous_state=receipt_state,
        graph=graph,
        target_node=attempt["target_node"],
        checkpoint=checkpoint,
        scope=scope,
        origin_ref=f"{trace_ref}:arrival",
        current_node=attempt["current_node"],
    )
    return {
        "assessments": assessments,
        "frame": frame,
        "trace_delta": entry_resolution_trace_delta(
            current_frame=attempt["attempt_frame"],
            projected_frame=frame,
            current_node=attempt["current_node"],
            target_node=attempt["target_node"],
            assessments=assessments,
            requirement_titles={
                requirement_id: str(item.get("title_zh") or requirement_id)
                for requirement_id, item in requirement_map(graph).items()
            },
        ),
        "event": entry_resolution_event_envelope(
            before_state=attempt["current_frame"],
            departure_state=attempt["departure_frame"],
            after_state=frame,
            trace_ref=trace_ref,
        ),
    }
