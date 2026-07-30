"""Exact idempotency lookup for isolated Graph continuation shadows."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson


def find_existing_shadow_continuation(
    conn: sqlite3.Connection,
    *,
    owner: str,
    prepared: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the most advanced exact shadow incarnation, if one exists."""
    if prepared.get("execution_mode") != "shadow":
        return None
    rows = conn.execute(
        """
        SELECT i.instance_id, i.work_package_id, i.graph_id, i.graph_version,
               i.product_group, i.workspace_id, i.mode, i.shadow_run_id,
               i.created_at AS instance_created_at,
               b.branch_id, b.hypothesis_branch_id, b.label,
               b.current_node, b.status, b.created_at, b.updated_at,
               t.evidence_json
        FROM research_graph_instances AS i
        JOIN research_graph_branches AS b
          ON b.instance_id=i.instance_id
        JOIN research_graph_trace AS t
          ON t.instance_id=i.instance_id AND t.branch_id=b.branch_id
        WHERE i.owner=?
          AND i.graph_id=?
          AND i.graph_version=?
          AND i.mode='shadow'
          AND i.shadow_run_id=?
          AND b.is_current_incarnation=1
        ORDER BY b.updated_at DESC, i.created_at DESC, t.created_at ASC
        """,
        (
            owner,
            prepared["graph_id"],
            prepared["target_graph_version"],
            prepared["shadow_run_id"],
        ),
    ).fetchall()
    for row in rows:
        try:
            evidence = orjson.loads(row["evidence_json"])
        except (TypeError, orjson.JSONDecodeError):
            continue
        if evidence.get("graph_continuation") != prepared["descriptor"]:
            continue
        return {
            "instance_id": str(row["instance_id"]),
            "work_package_id": str(row["work_package_id"]),
            "owner": owner,
            "graph_id": str(row["graph_id"]),
            "graph_version": int(row["graph_version"]),
            "product_group": str(row["product_group"]),
            "workspace_id": str(row["workspace_id"]),
            "mode": str(row["mode"]),
            "shadow_run_id": str(row["shadow_run_id"]),
            "branches": [{
                "branch_id": str(row["branch_id"]),
                "hypothesis_branch_id": str(row["hypothesis_branch_id"]),
                "is_current_incarnation": True,
                "instance_id": str(row["instance_id"]),
                "label": str(row["label"]),
                "current_node": str(row["current_node"]),
                "status": str(row["status"]),
                "created_at": float(row["created_at"]),
                "updated_at": float(row["updated_at"]),
            }],
            "created_at": float(row["instance_created_at"]),
            "reused": True,
        }
    return None
