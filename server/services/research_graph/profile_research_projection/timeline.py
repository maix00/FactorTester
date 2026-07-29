"""Timeline step projection and resolvable object links."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson

from server.services.research_graph.report_checkpoint import (
    transition_step_projection,
)
from .refs import (
    MAX_PROJECTION_BYTES,
    bounded_projection,
    encode_cursor,
    parse_research_ref,
)
from .summary import _json_object, _profile_ref
from .timeline_links import object_hrefs


def _bounded_transition_page(
    *,
    rows: list[sqlite3.Row],
    research_ref: str,
    page_limit: int,
    identity: dict[str, Any],
    placement: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return the largest ordered timeline prefix within the HTTP budget."""
    visible_rows = rows[:page_limit]
    items = [
        _transition_step(
            row,
            research_ref,
            placement=placement[str(row["trace_id"])],
        )
        for row in visible_rows
    ]
    smallest_candidate: dict[str, Any] | None = None
    minimum_count = 1 if items else 0
    for count in range(len(items), minimum_count - 1, -1):
        has_more = len(rows) > count
        next_cursor = (
            encode_cursor(
                kind="timeline",
                at=float(visible_rows[count - 1]["created_at"]),
                identifier=str(visible_rows[count - 1]["trace_id"]),
            )
            if has_more and count
            else None
        )
        candidate = {
            **identity,
            "items": items[:count],
            "next_cursor": next_cursor,
        }
        smallest_candidate = candidate
        if len(orjson.dumps(candidate)) <= MAX_PROJECTION_BYTES:
            return bounded_projection(candidate)
    # A single transition is indivisible audit evidence. If it cannot fit,
    # retain the existing explicit protocol failure instead of dropping it.
    return bounded_projection(smallest_candidate or {
        **identity,
        "items": [],
        "next_cursor": None,
    })


def _transition_step(
    row: sqlite3.Row,
    research_ref: str,
    *,
    placement: dict[str, Any],
) -> dict[str, Any]:
    fallback_instance_id, fallback_branch_id = parse_research_ref(research_ref)
    try:
        trace_instance_id = str(row["trace_instance_id"] or fallback_instance_id)
        trace_branch_id = str(row["trace_branch_id"] or fallback_branch_id)
    except (IndexError, KeyError):
        trace_instance_id = fallback_instance_id
        trace_branch_id = fallback_branch_id
    evidence = _json_object(row["evidence_json"])
    step = transition_step_projection(
        trace_id=str(row["trace_id"]),
        edge_id=str(row["edge_id"]),
        from_node=str(row["from_node"]),
        to_node=str(row["to_node"]),
        created_at=float(row["created_at"]),
        evidence=evidence,
    )
    step["status"] = (
        str(row["branch_status"])
        if str(row["trace_id"]) == str(row["latest_trace_id"])
        else "historical"
    )
    return {
        **step,
        "source_report_container": placement["source_report_container"],
        "report_container": placement["report_container"],
        "capability_detour": placement["capability_detour"],
        "research_ref": research_ref,
        "acting_profile_ref": _profile_ref(row, "acting_profile_ref"),
        "actor_ref": f"actor:{str(row['actor'])}",
        "object_hrefs": object_hrefs(
            step=step, evidence=evidence,
            instance_id=trace_instance_id, branch_id=trace_branch_id,
            trace_id=str(row["trace_id"]),
        ),
        "job_stream_hrefs": [
            f"/api/jobs/{ref.removeprefix('job:')}/stream"
            for ref in step["job_refs"]
        ],
    }
