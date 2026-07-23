"""Current Hypothesis Branch detail projection."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.services.research_graph.protocol import loads
from server.services.research_graph.report_checkpoint import (
    cycle_projection as _cycle_projection,
    named_refs as _named_refs,
    report_checkpoint_projection,
    safe_refs as _safe_refs,
)

from .refs import bounded_projection, work_package_ref_for
from .summary import _branch_summary, _json_object

_TERMINAL_JOB_STATUSES = frozenset({
    "cancelled", "failed", "paused", "succeeded",
})
_LIVE_JOB_STATUSES = frozenset({
    "planning", "queued", "running", "submitted",
})


def branch_projection(row: sqlite3.Row) -> dict[str, Any]:
    instance_id = str(row["instance_id"])
    work_package_id = str(row["work_package_id"] or instance_id)
    branch_id = str(row["branch_id"])
    evidence = _json_object(row["latest_trace_evidence_json"])
    cycle = _cycle_projection(evidence.get("research_cycle_checkpoint"))
    job_refs = _named_refs(evidence, "job_id", prefix="job:")
    run_refs = _named_refs(evidence, "run_id", prefix="run:")
    job_status = _first_named_text(evidence, "status", parent_key="facts")
    terminal = bool(cycle["closure"]) or str(row["status"]) == "paused"
    if job_status in _LIVE_JOB_STATUSES and job_refs:
        refresh = {
            "mode": "job_sse",
            "href": f"/api/jobs/{job_refs[0].removeprefix('job:')}/stream",
            "terminal": False,
        }
    elif terminal or job_status in _TERMINAL_JOB_STATUSES:
        refresh = {"mode": "stopped", "terminal": True}
    else:
        refresh = {
            "mode": "conditional_etag",
            "minimum_interval_seconds": 5,
            "only_while_visible": True,
            "terminal": False,
        }
    value = {
        "schema_version": 2,
        **_branch_summary(row),
        "capability_resolution_ref": (
            "branch-resolution:"
            f"{instance_id}:{branch_id}:"
            f"{str(row['current_capability_resolution_hash'])}"
        ),
        "trial_stage": _json_object(
            row["trial_stage_projection_json"]
        ),
        "evidence_refs": _safe_refs(
            loads(row["evidence_refs_json"]) or []
        ),
        "omitted_evidence_count": int(
            row["omitted_evidence_count"]
        ),
        "research_cycle": cycle,
        "job_refs": job_refs,
        "run_refs": run_refs,
        "timeline_href": (
            f"/api/profile-research/"
            f"{work_package_ref_for(work_package_id)}/branches/"
            f"{branch_id}/timeline"
        ),
        "refresh": refresh,
        "report_checkpoint": (
            report_checkpoint_projection(
                instance_id=str(row["instance_id"]),
                work_package_id=work_package_id,
                branch_id=str(row["branch_id"]),
                workspace_id=str(row["workspace_id"]),
                graph_id=str(row["graph_id"]),
                graph_version=int(row["graph_version"]),
                title=str(row["label"]),
                product_group=str(row["product_group"]),
                current_node=str(row["current_node"]),
                status=str(row["status"]),
                trace_id=str(row["latest_trace_id"]),
                edge_id=str(row["latest_trace_edge_id"]),
                from_node=str(row["latest_trace_from_node"]),
                created_at=float(row["latest_trace_created_at"]),
                checkpoint=evidence.get("research_cycle_checkpoint"),
                trace_evidence=evidence,
                evidence_refs=loads(row["evidence_refs_json"]) or [],
                omitted_evidence_count=int(
                    row["omitted_evidence_count"]
                ),
            )
            if row["latest_trace_id"]
            else None
        ),
    }
    return bounded_projection(value)


def _first_named_text(
    value: Any,
    key: str,
    *,
    parent_key: str,
) -> str:
    if isinstance(value, dict):
        parent = value.get(parent_key)
        if isinstance(parent, dict) and isinstance(parent.get(key), str):
            return str(parent[key])
        for child in value.values():
            found = _first_named_text(
                child,
                key,
                parent_key=parent_key,
            )
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_named_text(
                child,
                key,
                parent_key=parent_key,
            )
            if found:
                return found
    return ""
