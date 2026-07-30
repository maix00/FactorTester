"""Resolve Graph-owned requirement classes with branch-local obligations.

The requirement catalog owns stable categories and versioned Entry Requirement
subclasses.  A Research Agent registers each concrete Verification Obligation
under one category; it does not bind the obligation directly to a subclass.
At node entry or departure, the Agent maps category-compatible obligations to
the active subclasses through a coverage decision.  Eligible receipts bind the
requirement revision, obligation revisions, scope, and Research Cycle
checkpoint.  Report coverage is an independent transition gate and never
substitutes for semantic Entry Requirement resolution.
"""

from .service import assess_departure, project_arrival
from .frame import (
    active_entry_requirement_ids,
    compact_entry_resolution_frame,
    initial_entry_resolution_frame,
)

__all__ = [
    "active_entry_requirement_ids",
    "assess_departure",
    "compact_entry_resolution_frame",
    "initial_entry_resolution_frame",
    "project_arrival",
]
