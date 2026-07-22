"""SQL projections for one Graph instance and Hypothesis Branch."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from server.services.research_graph.branch.projection import (
    serialize_capability_resolution,
)
from server.services.research_graph.protocol import loads


CURRENT_BRANCH_CONTEXT_SQL = """
    SELECT i.*, b.*, t.edge_id AS latest_trace_edge_id,
           t.evidence_json AS latest_trace_evidence_json,
           COALESCE(w.lifecycle, 'active') AS work_package_lifecycle,
           COALESCE(w.revision, 1) AS work_package_revision
    FROM research_graph_instances i
    JOIN research_graph_branches b
      ON b.instance_id=i.instance_id
    LEFT JOIN research_graph_trace t
      ON t.trace_id=b.latest_trace_id
    LEFT JOIN research_work_packages w
      ON w.owner=i.owner
     AND w.work_package_id=COALESCE(
         NULLIF(i.work_package_id, ''), i.instance_id
     )
    WHERE i.instance_id=? AND b.branch_id=? AND i.owner=?
"""


def branch_payload(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "branch_id": str(row["branch_id"]),
        "hypothesis_branch_id": str(
            row["hypothesis_branch_id"] or row["branch_id"]
        ),
        "is_current_incarnation": bool(row["is_current_incarnation"]),
        "instance_id": str(row["instance_id"]),
        "work_package_id": str(
            row["work_package_id"] or row["instance_id"]
        ),
        "created_by_profile_ref": str(
            row["created_by_profile_ref"] or ""
        ),
        "current_owner_profile_ref": str(
            row["current_owner_profile_ref"] or ""
        ),
        "label": str(row["label"]),
        "current_node": str(row["current_node"]),
        "status": str(row["status"]),
        "work_package_lifecycle": str(
            row["work_package_lifecycle"] or "active"
        ),
        "work_package_revision": int(row["work_package_revision"] or 1),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def store_current_branch_resolution(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
    node_id: str,
    resolution: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    value, serialized, semantic_hash = serialize_capability_resolution(
        resolution,
        node_id=node_id,
    )
    cursor = conn.execute(
        """
        UPDATE research_graph_branches
        SET current_capability_resolution_json=?,
            current_capability_resolution_hash=?,
            updated_at=?
        WHERE instance_id=? AND branch_id=? AND current_node=?
          AND current_capability_resolution_hash<>?
        """,
        (
            serialized,
            semantic_hash,
            time.time(),
            instance_id,
            branch_id,
            node_id,
            semantic_hash,
        ),
    )
    return value, max(int(cursor.rowcount), 0)


def load_current_branch_resolution(row: sqlite3.Row) -> dict[str, Any]:
    return loads(row["current_capability_resolution_json"]) or {
        "node_id": str(row["current_node"])
    }


def load_instance_branch_row(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT i.*, b.*,
               COALESCE(w.lifecycle, 'active') AS work_package_lifecycle,
               COALESCE(w.revision, 1) AS work_package_revision
        FROM research_graph_instances i
        JOIN research_graph_branches b
          ON b.instance_id=i.instance_id
        LEFT JOIN research_work_packages w
          ON w.owner=i.owner
         AND w.work_package_id=COALESCE(
             NULLIF(i.work_package_id, ''), i.instance_id
         )
        WHERE i.instance_id=? AND b.branch_id=? AND i.owner=?
        """,
        (instance_id, branch_id, owner),
    ).fetchone()


def load_instance_branch_with_latest_trace(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> sqlite3.Row | None:
    """Load current branch and its checkpoint carrier by primary-key join."""
    return conn.execute(
        CURRENT_BRANCH_CONTEXT_SQL,
        (instance_id, branch_id, owner),
    ).fetchone()
