"""Exact database projection and validation for shadow ownership repair."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

import orjson


INSTANCE_TABLES = (
    "trial_plan_action_adjudication_receipts",
    "research_report_item_checkpoints",
    "research_graph_objects",
    "research_graph_capability_detours",
    "research_graph_trace",
)


def instance_projection(
    conn: sqlite3.Connection,
    instance_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT i.*, b.branch_id, b.current_node, b.status, b.latest_trace_id
        FROM research_graph_instances AS i
        JOIN research_graph_branches AS b ON b.instance_id=i.instance_id
        WHERE i.instance_id=?
        """,
        (instance_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"shadow instance was not found: {instance_id}")
    traces = conn.execute(
        """
        SELECT trace_id, evidence_json FROM research_graph_trace
        WHERE instance_id=? AND branch_id=? ORDER BY created_at, trace_id
        """,
        (instance_id, row["branch_id"]),
    ).fetchall()
    if not traces:
        raise ValueError("shadow instance has no bootstrap trace")
    descriptor = (
        orjson.loads(traces[0]["evidence_json"])
        .get("graph_continuation") or {}
    )
    return {
        "instance_id": str(row["instance_id"]),
        "branch_id": str(row["branch_id"]),
        "old_work_package_id": str(row["work_package_id"]),
        "owner": str(row["owner"]),
        "workspace_id": str(row["workspace_id"]),
        "mode": str(row["mode"]),
        "graph_id": str(row["graph_id"]),
        "graph_version": int(row["graph_version"]),
        "shadow_run_id": str(row["shadow_run_id"]),
        "source_instance_id": str(descriptor.get("source_instance_id") or ""),
        "source_branch_id": str(descriptor.get("source_branch_id") or ""),
        "descriptor_work_package_id": str(
            descriptor.get("work_package_id") or ""
        ),
        "shadow_proposal_id": str(
            descriptor.get("shadow_proposal_id") or ""
        ),
        "current_node": str(row["current_node"]),
        "status": str(row["status"]),
        "latest_trace_id": str(row["latest_trace_id"]),
        "trace_count": len(traces),
        "graph_object_count": count(
            conn, "research_graph_objects", instance_id,
        ),
        "adjudication_count": count(
            conn, "trial_plan_action_adjudication_receipts", instance_id,
        ),
    }


def validate_shadow(
    row: dict[str, Any],
    *,
    owner: str,
    source_work_package_id: str,
    workspace_id: str,
) -> None:
    if row["owner"] != owner or row["workspace_id"] != workspace_id:
        raise ValueError("shadow migration crosses owner or workspace")
    if row["mode"] != "shadow":
        raise ValueError("shadow migration target is not a shadow instance")
    if row["old_work_package_id"] != row["instance_id"]:
        raise ValueError("shadow is not affected by the split Work Package bug")
    if (
        row["source_instance_id"] != source_work_package_id
        or row["descriptor_work_package_id"] != source_work_package_id
    ):
        raise ValueError("shadow continuation lineage does not match source")


def count(conn: sqlite3.Connection, table: str, instance_id: str) -> int:
    return int(conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE instance_id=?",
        (instance_id,),
    ).fetchone()[0])


def canonical_hash(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
