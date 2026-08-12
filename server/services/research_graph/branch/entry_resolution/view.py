"""Derived context projection for canonical entry-resolution state."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .stack_state import (
    active_frame,
    canonical_entry_resolution_state,
    text_ids,
)


def active_entry_requirement_ids(
    *, frame: dict[str, Any], current_node: str,
) -> list[str] | None:
    active = active_frame(frame)
    if active is None or str(active.get("target_node") or "") != current_node:
        return None
    return text_ids(active.get("unresolved_entry_requirement_refs"))


def compact_entry_resolution_frame(
    frame: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(frame, dict) or not frame:
        return None
    state = canonical_entry_resolution_state(frame)
    active = active_frame(state)
    value: dict[str, Any] = {
        "schema_version": 2,
        "status": str(active.get("status") or "resolved") if active else "resolved",
        "depth": len(state["frames"]),
        "active_frame_id": (
            str(active.get("entry_attempt_id") or "") if active else ""
        ),
        "reused_requirement_count": len(
            text_ids(
                active.get("reused_entry_requirement_refs")
                if active else []
            )
        ),
        "cached_receipt_count": len(state["assessment_receipts"]),
    }
    if active is None:
        return value
    for field in (
        "entry_attempt_id", "graph_ref", "target_node",
        "origin_checkpoint_ref", "blocking_obligation_refs",
        "entry_requirement_refs", "unresolved_entry_requirement_refs",
        "selected_route", "dispatch_refs", "completion_refs",
        "resume_guard_hash",
    ):
        if field in active:
            value[field] = deepcopy(active[field])
    return value
