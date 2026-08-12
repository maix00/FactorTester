"""Public API for canonical nested entry-resolution return frames."""

from .stack_routing import advance_active_frame, project_target_frame
from .stack_state import active_frame, canonical_entry_resolution_state
from .events import (
    entry_resolution_event_envelope,
    entry_resolution_stack_hash,
)
from .guard import resume_guard_hash, resume_guard_matches

__all__ = [
    "active_frame",
    "advance_active_frame",
    "canonical_entry_resolution_state",
    "entry_resolution_event_envelope",
    "entry_resolution_stack_hash",
    "project_target_frame",
    "resume_guard_hash",
    "resume_guard_matches",
]
