"""Hash-chain replay for entry-resolution trace envelopes."""

from __future__ import annotations

from typing import Any

from .event_validation import canonical_entry_resolution_event
from .events import entry_resolution_stack_hash


def empty_entry_stack_identity() -> tuple[str, int]:
    return entry_resolution_stack_hash({}), 0


def replay_entry_resolution_event(
    *,
    event: Any,
    trace_id: str,
    stack_hash: str,
    depth: int,
) -> tuple[str, int]:
    if event is None:
        return stack_hash, depth
    value = canonical_entry_resolution_event(event)
    if value["trace_ref"] != f"trace:{trace_id}":
        raise ValueError("entry_resolution_event trace_ref does not match")
    if (
        value["stack_hash_before"] != stack_hash
        or value["depth_before"] != depth
    ):
        raise ValueError("entry_resolution_event chain is discontinuous")
    return value["stack_hash_after"], value["depth_after"]
