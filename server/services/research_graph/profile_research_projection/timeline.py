"""Timeline step projection and resolvable object links."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson

from server.services.research_graph.report_checkpoint import (
    transition_step_projection,
)
from server.services.research_graph.trial_plan import (
    canonical_trial_plan,
    trial_plan_hash,
)

from .refs import (
    MAX_PROJECTION_BYTES,
    bounded_projection,
    encode_cursor,
    parse_research_ref,
)
from .summary import _json_object, _profile_ref


def _bounded_transition_page(
    *,
    rows: list[sqlite3.Row],
    research_ref: str,
    page_limit: int,
    identity: dict[str, Any],
) -> dict[str, Any]:
    """Return the largest ordered timeline prefix within the HTTP budget."""
    visible_rows = rows[:page_limit]
    items = [_transition_step(row, research_ref) for row in visible_rows]
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
    object_refs = [
        *step["obligation_refs"], *step["claim_refs"], *step["delta_refs"],
        *step["run_refs"],
    ]
    plan = evidence.get("trial_plan")
    if isinstance(plan, dict):
        try:
            canonical_plan = canonical_trial_plan(plan)
        except ValueError:
            canonical_plan = None
        if canonical_plan is not None:
            resolvable_plan_refs = {
                "trial-plan:" + canonical_plan["trial_plan_id"],
                "trial-plan:sha256:" + trial_plan_hash(canonical_plan),
            }
            object_refs.extend(
                ref for ref in step["trial_plan_refs"]
                if ref in resolvable_plan_refs
            )
    available_evidence = {
        "evidence:" + str(item.get("envelope_hash"))
        for item in _checkpoint_evidence_envelopes(
            evidence.get("server_evidence")
        )
    }
    object_refs.extend(
        ref for ref in step["evidence_refs"]
        if ref in available_evidence
    )
    return {
        **step,
        "research_ref": research_ref,
        "acting_profile_ref": _profile_ref(row, "acting_profile_ref"),
        "actor_ref": f"actor:{str(row['actor'])}",
        "object_hrefs": [
            (
                "/api/research-graph-instances/"
                f"{trace_instance_id}/branches/"
                f"{trace_branch_id}/cycle-objects/"
                f"{_cycle_object_type(ref)}/{ref.split(':', 1)[1]}"
                f"?trace_id={str(row['trace_id'])}"
            )
            for ref in object_refs
        ],
        "job_stream_hrefs": [
            f"/api/jobs/{ref.removeprefix('job:')}/stream"
            for ref in step["job_refs"]
        ],
    }


def _checkpoint_evidence_envelopes(value: Any):
    if isinstance(value, dict):
        if (
            value.get("schema_version") == 2
            and isinstance(value.get("envelope_hash"), str)
            and isinstance(value.get("evidence_kind"), str)
        ):
            yield value
            return
        for child in value.values():
            yield from _checkpoint_evidence_envelopes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _checkpoint_evidence_envelopes(child)


def _cycle_object_type(reference: str) -> str:
    kind = reference.split(":", 1)[0]
    if kind == "trial-plan":
        return "trial_plan"
    return kind
