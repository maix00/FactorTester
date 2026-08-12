"""Authoritative report placement for one bounded timeline page."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.services.research_graph.branch.capability_detour import (
    project_trace_rows,
)


def placement_by_trace(
    *,
    page_rows: list[sqlite3.Row],
    boundary_rows: list[sqlite3.Row],
) -> dict[str, dict[str, Any]]:
    """Replay only detour boundaries plus visible transitions."""
    merged = {
        str(row["trace_id"]): _replay_row(row)
        for row in boundary_rows
        if row["trace_id"] is not None
    }
    merged.update({
        str(row["trace_id"]): _replay_row(row)
        for row in page_rows
        if row["trace_id"] is not None
    })
    ordered = sorted(
        merged.values(),
        key=lambda row: (
            float(row["created_at"]),
            int(row["trace_rowid"]),
            str(row["trace_id"]),
        ),
    )
    return project_trace_rows(ordered)["items"]


def _replay_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "trace_id": str(row["trace_id"]),
        "edge_id": str(row["edge_id"]),
        "from_node": str(row["from_node"]),
        "to_node": str(row["to_node"]),
        "created_at": float(row["created_at"]),
        "trace_rowid": int(row["trace_rowid"]),
        "evidence_json": str(row["evidence_json"] or "{}"),
    }
