"""Verification of checkpoint continuity carried by Graph trace rows."""

from __future__ import annotations

from typing import Any

from .replay import (
    replay_research_cycle_events,
    validate_research_cycle_checkpoint,
)


def verify_research_cycle_trace(
    *,
    previous_checkpoint: dict[str, Any] | None,
    previous_trace_id: str,
    event: Any,
    projected_checkpoint: Any,
    resolved_events: list[dict[str, Any]] | None = None,
    requirement_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute one trace checkpoint without trusting its projection."""
    if not isinstance(event, dict) or event.get("schema_version") != 1:
        raise ValueError("invalid research_cycle trace event")
    expected_parent = (
        f"trace:{previous_trace_id}" if previous_trace_id else ""
    )
    if event.get("parent_trace_ref", "") != expected_parent:
        raise ValueError("research_cycle trace parent mismatch")
    initial = event.get("initial_checkpoint")
    if previous_checkpoint is None:
        if event.get("bootstrap_checkpoint") is not True:
            raise ValueError("research_cycle trace lacks bootstrap marker")
        if initial is not None:
            raise ValueError("research_cycle trace embeds duplicate bootstrap")
        base = validate_research_cycle_checkpoint(projected_checkpoint)
    else:
        if initial is not None or "bootstrap_checkpoint" in event:
            raise ValueError("research_cycle trace repeats initial checkpoint")
        base = previous_checkpoint
    if event.get("checkpoint_before_hash") != base["projection_hash"]:
        raise ValueError("research_cycle checkpoint_before_hash mismatch")
    events = (
        resolved_events
        if resolved_events is not None
        else event.get("events")
    )
    if not isinstance(events, list):
        raise ValueError("research_cycle trace events must be an array")
    if resolved_events is not None:
        from server.services.research_graph.branch.trace_compaction import (
            compact_research_cycle_event_receipts,
        )

        if event.get("event_receipts") != (
            compact_research_cycle_event_receipts(events)
        ):
            raise ValueError("research_cycle event receipts mismatch")
    if previous_checkpoint is None and events:
        raise ValueError("research_cycle bootstrap cannot adjudicate events")
    recomputed = replay_research_cycle_events(
        base,
        events=events,
        expected_base_hash=base["projection_hash"],
        requirement_catalog=requirement_catalog,
    )
    projected = validate_research_cycle_checkpoint(projected_checkpoint)
    if projected["projection_hash"] != recomputed["projection_hash"]:
        raise ValueError("research_cycle projected checkpoint mismatch")
    return recomputed
