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


JOB_EVIDENCE_MODE = "job_evidence"
PRE_TRIAL_CHECKPOINT_MODE = "pre_trial_checkpoint"
SAME_NODE_REENTRY_MODE = "same_node_reentry"
JOB_EVIDENCE_TARGET_NODE = "job_evidence_ready"
PRE_TRIAL_TARGET_NODE = "capability_gap"


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
    target_node = str(prepared["target_node"])
    target_status = str(prepared["target_status"])
    _, resolution_json, resolution_hash = serialize_capability_resolution(
        {"node_id": target_node},
        node_id=target_node,
    )
    conn.execute(
        """
        UPDATE research_graph_instances
        SET work_package_id=instance_id
        WHERE instance_id=? AND work_package_id=''
        """,
        (prepared["descriptor"]["source_instance_id"],),
    )
    conn.execute(
        """
        UPDATE research_graph_branches
        SET hypothesis_branch_id=branch_id
        WHERE branch_id=? AND hypothesis_branch_id=''
        """,
        (prepared["descriptor"]["source_branch_id"],),
    )
    retired = conn.execute(
        """
        UPDATE research_graph_branches SET is_current_incarnation=0
        WHERE branch_id=? AND is_current_incarnation=1
        """,
        (prepared["descriptor"]["source_branch_id"],),
    )
    if retired.rowcount != 1:
        raise ValueError("Graph continuation source incarnation changed")
    conn.execute(
        """
        INSERT INTO research_graph_instances (
            instance_id, work_package_id, owner, created_by_profile_ref,
            current_owner_profile_ref, graph_id, graph_version, product_group,
            workspace_id, mode, shadow_run_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?)
        """,
        (
            instance_id,
            prepared["work_package_id"],
            owner,
            prepared["created_by_profile_ref"],
            prepared["current_owner_profile_ref"],
            prepared["graph_id"],
            prepared["target_graph_version"],
            prepared["product_group"],
            prepared["workspace_id"],
            prepared["execution_mode"],
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO research_graph_branches (
            branch_id, hypothesis_branch_id, is_current_incarnation,
            instance_id,
            label, current_node, status,
            current_capability_resolution_json,
            current_capability_resolution_hash,
            current_trial_plan_hash, trial_stage_projection_json,
            entry_resolution_frame_json,
            evidence_refs_json, omitted_evidence_count, latest_trace_id,
            created_at, updated_at
        ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            branch_id,
            prepared["hypothesis_branch_id"],
            instance_id,
            f"continuation-v{prepared['target_graph_version']}",
            target_node,
            target_status,
            resolution_json,
            resolution_hash,
            prepared["current_trial_plan_hash"],
            prepared["trial_stage_projection_json"],
            prepared["entry_resolution_frame_json"],
            orjson.dumps(prepared["evidence_refs"]).decode(),
            int(prepared["omitted_evidence_count"]),
            trace_id,
            now,
            now,
        ),
    )
    checkpoint = prepared["checkpoint"]
    descriptor = prepared["descriptor"]
    source_trace_ref = f"trace:{descriptor['source_trace_id']}"
    evidence: dict[str, Any] = {
        "graph_continuation": {
            **descriptor,
            "authorization_ref": (
                f"maintenance-case:{authorization_id}"
            ),
        },
        "evidence_refs": prepared["evidence_refs"],
        "research_cycle": {
            "schema_version": 1,
            "parent_trace_ref": source_trace_ref,
            "checkpoint_before_hash": checkpoint["projection_hash"],
            "events": [],
        },
        "research_cycle_checkpoint": checkpoint,
        "report_lineage": {
            "status": "linked",
            "predecessor_checkpoint_ref": source_trace_ref,
            "source_branch_ref": (
                "graph-branch:"
                f"{descriptor['source_instance_id']}:"
                f"{descriptor['source_branch_id']}"
            ),
        },
    }
    if prepared["continuation_mode"] == JOB_EVIDENCE_MODE:
        evidence["server_evidence"] = {
            "job_attempt": prepared["envelope"],
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
            target_node,
            target_node,
            serialize_bounded_trace_evidence(evidence),
            owner,
            now,
        ),
    )
