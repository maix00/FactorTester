"""Compatibility imports for the split Entry Resolution implementation."""

from .initial import initial_entry_resolution_frame
from .stack_routing import advance_active_frame
from .trace_delta import entry_resolution_trace_delta
from .view import (
    active_entry_requirement_ids,
    compact_entry_resolution_frame,
)


def advance_entry_resolution_frame(
    *,
    frame,
    current_node,
    target_node,
    assessments,
):
    return advance_active_frame(
        state=frame,
        current_node=current_node,
        target_node=target_node,
        assessments=assessments,
    )

__all__ = [
    "active_entry_requirement_ids",
    "advance_entry_resolution_frame",
    "compact_entry_resolution_frame",
    "entry_resolution_trace_delta",
    "initial_entry_resolution_frame",
]
