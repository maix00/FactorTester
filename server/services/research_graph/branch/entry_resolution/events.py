"""Ordered trace envelope for entry-resolution stack events."""

from __future__ import annotations

from typing import Any

from server.services.research_graph.protocol import json_hash

from .event_derivation import arrival_events, departure_events
from .stack_state import canonical_entry_resolution_state


def entry_resolution_event_envelope(
    *,
    before_state: Any,
    departure_state: Any,
    after_state: Any,
    trace_ref: str,
) -> dict[str, Any] | None:
    before = canonical_entry_resolution_state(before_state)
    departure = canonical_entry_resolution_state(departure_state)
    after = canonical_entry_resolution_state(after_state)
    events = departure_events(before, departure)
    events.extend(arrival_events(departure, after))
    if not events:
        return None
    return {
        "schema_version": 2,
        "trace_ref": trace_ref,
        "stack_hash_before": entry_resolution_stack_hash(before),
        "stack_hash_after": entry_resolution_stack_hash(after),
        "depth_before": len(before["frames"]),
        "depth_after": len(after["frames"]),
        "events": [
            _event_record(event, frame, ordinal=index)
            for index, (event, frame) in enumerate(events)
        ],
    }


def entry_resolution_stack_hash(state: Any) -> str:
    value = canonical_entry_resolution_state(state)
    return json_hash(value["frames"])
def _event_record(
    event: str,
    frame: dict[str, Any],
    *,
    ordinal: int,
) -> dict[str, Any]:
    attempt_id = str(frame.get("entry_attempt_id") or "")
    target_node = str(frame.get("target_node") or "")
    return {
        "ordinal": ordinal,
        "event": event,
        "entry_attempt_id": attempt_id,
        "target_node": target_node,
        "report_item": {
            "kind": f"entry_resolution.{event}",
            "entry_attempt_id": attempt_id,
            "target_node": target_node,
        },
    }
