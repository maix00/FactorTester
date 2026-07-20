"""Server-owned transition facts derived from the current branch projection."""

from __future__ import annotations

import sqlite3
from typing import Any


def system_transition_guard_facts(
    *,
    branch_row: sqlite3.Row | dict[str, Any],
    cycle_checkpoint: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return bounded facts an Agent must not be allowed to self-assert."""
    closure = (
        cycle_checkpoint.get("closure")
        if isinstance(cycle_checkpoint, dict)
        else None
    )
    return {
        "gap_origin_edge_id": str(
            branch_row["latest_trace_edge_id"] or ""
        ),
        "bounded_closure_disposition": (
            str(closure.get("disposition") or "")
            if isinstance(closure, dict)
            else ""
        ),
    }
