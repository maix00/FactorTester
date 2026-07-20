"""Atomic row projection for an authorized Graph continuation."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson

from server.services.research_graph.branch.projection import (
    serialize_capability_resolution,
)
from server.services.research_graph.protocol import (
    serialize_bounded_trace_evidence,
)


TARGET_NODE = "job_evidence_ready"


def insert_continuation(
    conn: sqlite3.Connection,
    *,
    prepared: dict[str, Any],
    owner: str,
    instance_id: str,
    branch_id: str,
    trace_id: str,
    authorization_id: str,
    now: float,
) -> None:
    """Insert one instance, branch, and bootstrap trace in one transaction."""
    _, resolution_json, resolution_hash = serialize_capability_resolution(
        {"node_id": TARGET_NODE},
        node_id=TARGET_NODE,
    )
    conn.execute(
        """
        INSERT INTO research_graph_instances (
            instance_id, owner, graph_id, graph_version, product_group,
            workspace_id, mode, shadow_run_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'live', '', ?)
        """,
        (
            instance_id,
            owner,
            prepared["graph_id"],
            prepared["target_graph_version"],
            prepared["product_group"],
            prepared["workspace_id"],
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO research_graph_branches (
            branch_id, instance_id, label, current_node, status,
            current_capability_resolution_json,
            current_capability_resolution_hash,
            current_trial_plan_hash, trial_stage_projection_json,
            evidence_refs_json, omitted_evidence_count, latest_trace_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, 0, ?, ?, ?)
        """,
        (
            branch_id,
            instance_id,
            f"continuation-v{prepared['target_graph_version']}",
            TARGET_NODE,
            resolution_json,
            resolution_hash,
            prepared["current_trial_plan_hash"],
            prepared["trial_stage_projection_json"],
            orjson.dumps([
                "evidence:" + prepared["envelope"]["envelope_hash"]
            ]).decode(),
            trace_id,
            now,
            now,
        ),
    )
    checkpoint = prepared["checkpoint"]
    evidence = {
        "graph_continuation": {
            **prepared["descriptor"],
            "authorization_ref": (
                f"maintenance-case:{authorization_id}"
            ),
        },
        "server_evidence": {
            "job_attempt": prepared["envelope"],
        },
        "evidence_refs": [
            "evidence:" + prepared["envelope"]["envelope_hash"],
        ],
        "research_cycle": {
            "schema_version": 1,
            "parent_trace_ref": "",
            "checkpoint_before_hash": checkpoint["projection_hash"],
            "events": [],
            "bootstrap_checkpoint": True,
        },
        "research_cycle_checkpoint": checkpoint,
    }
    conn.execute(
        """
        INSERT INTO research_graph_trace (
            trace_id, instance_id, branch_id, edge_id, from_node, to_node,
            evidence_json, telemetry_json, actor, created_at
        ) VALUES (?, ?, ?, '__graph_continuation__', ?, ?, ?, '{}', ?, ?)
        """,
        (
            trace_id,
            instance_id,
            branch_id,
            TARGET_NODE,
            TARGET_NODE,
            serialize_bounded_trace_evidence(evidence),
            owner,
            now,
        ),
    )
