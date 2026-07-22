"""Lifecycle operations for Graph instances and Hypothesis Branches."""

from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any

import settings as Settings
from server.services.research_graph.branch.projection import (
    normalize_capability_resolution,
    serialize_capability_resolution,
)
from server.services.research_graph.branch.repository import (
    branch_payload,
    load_instance_branch_row,
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.branch.research_cycle import (
    checkpoint_from_branch_row,
)
from server.services.research_graph.branch.profile_identity import (
    optional_profile_ref,
)
from server.services.research_graph.capability_resolution import (
    missing_required_capabilities,
    validate_resolution_against_node,
)
from server.services.research_graph.active_pointer import load_active_graph
from server.services.research_graph.protocol import (
    GraphActivationBlocked,
    serialize_bounded_trace_evidence,
)
from server.services.research_graph.versions import load_graph
from server.services.research_graph.work_packages import (
    insert_active,
    require_active,
)
from tools.data.sqlite.db import connect_sqlite


def create_graph_instance(
    *,
    graph_id: str,
    owner: str,
    product_group: str,
    workspace_id: str,
    capability_resolution: dict[str, Any],
    shadow_graph_version: int | None = None,
    shadow_run_id: str = "",
    profile_ref: str = "",
) -> dict[str, Any]:
    profile_ref = optional_profile_ref(profile_ref)
    if shadow_graph_version is not None:
        active = load_graph(
            graph_id=graph_id,
            version=int(shadow_graph_version),
        )
        if active is None or active.get("lifecycle") != "draft":
            raise GraphActivationBlocked("shadow draft graph not found")
        if not shadow_run_id:
            raise ValueError("shadow_run_id is required for a shadow instance")
        mode = "shadow"
    else:
        if shadow_run_id:
            raise ValueError("shadow_run_id is only valid in shadow mode")
        active = load_active_graph(graph_id=graph_id)
        if active is None:
            raise GraphActivationBlocked("active graph not found")
        mode = "live"
    entry_node = str(
        active.get("entry_node")
        or ((active.get("nodes") or [{}])[0].get("node_id") or "")
    )
    declared_nodes = {
        str(node.get("node_id") or "") for node in active.get("nodes") or []
    }
    if not entry_node or entry_node not in declared_nodes:
        raise ValueError("active graph entry_node is invalid")
    entry = next(
        node
        for node in active.get("nodes") or []
        if str(node.get("node_id") or "") == entry_node
    )
    instance_id = uuid.uuid4().hex
    branch_id = uuid.uuid4().hex
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        if mode == "shadow":
            try:
                run = conn.execute(
                    """
                    SELECT run_id FROM research_runs
                    WHERE run_id=? AND owner=? AND workspace_id=?
                    AND kind='factor_research'
                    """,
                    (shadow_run_id, owner, workspace_id),
                ).fetchone()
            except sqlite3.OperationalError as exc:
                raise ValueError(
                    "research run schema is not initialized"
                ) from exc
            if run is None:
                raise ValueError(
                    "shadow_run_id must reference an owned research run "
                    "in the same workspace"
                )
        local_resolution = normalize_capability_resolution(
            capability_resolution,
            node_id=entry_node,
        )
        validate_resolution_against_node(
            graph=active,
            node=entry,
            resolution=local_resolution,
        )
        missing_entry = missing_required_capabilities(
            entry,
            local_resolution,
        )
        if missing_entry:
            raise ValueError(
                "entry node has unresolved capabilities: "
                + ", ".join(missing_entry)
            )
        conn.execute(
            """
            INSERT INTO research_graph_instances (
                instance_id, work_package_id, owner, created_by_profile_ref,
                current_owner_profile_ref, graph_id, graph_version,
                product_group, workspace_id, mode, shadow_run_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                instance_id,
                owner,
                profile_ref,
                profile_ref,
                graph_id,
                int(active["version"]),
                product_group,
                workspace_id,
                mode,
                shadow_run_id,
                now,
            ),
        )
        insert_active(
            conn,
            owner=owner,
            work_package_id=instance_id,
            workspace_id=workspace_id,
            created_at=now,
        )
        _, resolution_json, resolution_hash = (
            serialize_capability_resolution(
                local_resolution,
                node_id=entry_node,
            )
        )
        conn.execute(
            """
            INSERT INTO research_graph_branches (
                branch_id, hypothesis_branch_id, is_current_incarnation,
                instance_id,
                label, current_node, status,
                current_capability_resolution_json,
                current_capability_resolution_hash,
                current_trial_plan_hash, created_at, updated_at
            ) VALUES (
                ?, ?, 1, ?, 'primary', ?, 'running', ?, ?, '', ?, ?
            )
            """,
            (
                branch_id,
                branch_id,
                instance_id,
                entry_node,
                resolution_json,
                resolution_hash,
                now,
                now,
            ),
        )
        branch = {
            "branch_id": branch_id,
            "hypothesis_branch_id": branch_id,
            "instance_id": instance_id,
            "label": "primary",
            "current_node": entry_node,
            "status": "running",
            "created_at": now,
            "updated_at": now,
        }
    return {
        "instance_id": instance_id,
        "work_package_id": instance_id,
        "owner": owner,
        "created_by_profile_ref": profile_ref,
        "current_owner_profile_ref": profile_ref,
        "graph_id": graph_id,
        "graph_version": int(active["version"]),
        "product_group": product_group,
        "workspace_id": workspace_id,
        "capability_resolution": local_resolution,
        "mode": mode,
        "shadow_run_id": shadow_run_id,
        "branches": [branch],
        "created_at": now,
    }


def load_graph_branch(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> dict[str, Any] | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = load_instance_branch_row(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
        )
    return branch_payload(row)


def fork_graph_branch(
    *,
    instance_id: str,
    source_branch_id: str,
    owner: str,
    label: str,
    acting_profile_ref: str = "",
) -> dict[str, Any]:
    acting_profile_ref = optional_profile_ref(acting_profile_ref)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        # Read the ownership projection and create the fork under one write
        # lock.  Otherwise a concurrent handoff could transfer the branch
        # after this check but before the fork marker is persisted.
        conn.execute("BEGIN IMMEDIATE")
        source = load_instance_branch_with_latest_trace(
            conn,
            instance_id=instance_id,
            branch_id=source_branch_id,
            owner=owner,
        )
        if source is None:
            raise KeyError("source branch not found")
        require_active(source)
        if not bool(source["is_current_incarnation"]):
            raise ValueError("source branch is not the current incarnation")
        current_owner_profile_ref = str(
            source["current_owner_profile_ref"] or ""
        )
        if current_owner_profile_ref and (
            acting_profile_ref != current_owner_profile_ref
        ):
            raise PermissionError("branch is owned by another Profile")
        branch_id = uuid.uuid4().hex
        trace_id = uuid.uuid4().hex
        now = time.time()
        checkpoint = checkpoint_from_branch_row(source)
        fork_evidence: dict[str, Any] = {
            "branch_fork": {
                "schema_version": 1,
                "source_branch_id": source_branch_id,
                "source_trace_ref": (
                    f"trace:{source['latest_trace_id']}"
                    if str(source["latest_trace_id"])
                    else None
                ),
                "checkpoint_node": str(source["current_node"]),
            },
        }
        if checkpoint is not None:
            fork_evidence.update({
                "research_cycle": {
                    "schema_version": 1,
                    "parent_trace_ref": "",
                    "checkpoint_before_hash": checkpoint["projection_hash"],
                    "events": [],
                    "bootstrap_checkpoint": True,
                },
                "research_cycle_checkpoint": checkpoint,
            })
        conn.execute(
            """
            INSERT INTO research_graph_branches (
                branch_id, hypothesis_branch_id, is_current_incarnation,
                instance_id, label, current_node, status,
                current_capability_resolution_json,
                current_capability_resolution_hash,
                current_trial_plan_hash, trial_stage_projection_json,
                evidence_refs_json,
                omitted_evidence_count, latest_trace_id,
                created_at, updated_at
            ) VALUES (?, ?, 1, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                branch_id,
                branch_id,
                instance_id,
                str(label or "fork").strip(),
                str(source["current_node"]),
                str(source["current_capability_resolution_json"]),
                str(source["current_capability_resolution_hash"]),
                str(source["current_trial_plan_hash"]),
                str(source["trial_stage_projection_json"]),
                str(source["evidence_refs_json"]),
                int(source["omitted_evidence_count"]),
                trace_id,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, acting_profile_ref,
                created_at
            ) VALUES (?, ?, ?, '__branch_fork__', ?, ?, ?, '{}', ?, ?, ?)
            """,
            (
                trace_id,
                instance_id,
                branch_id,
                str(source["current_node"]),
                str(source["current_node"]),
                serialize_bounded_trace_evidence(fork_evidence),
                owner,
                acting_profile_ref,
                now,
            ),
        )
    return {
        "branch_id": branch_id,
        "instance_id": instance_id,
        "label": str(label or "fork").strip(),
        "current_node": str(source["current_node"]),
        "status": "running",
        "created_at": now,
        "updated_at": now,
    }
