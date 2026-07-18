"""Lifecycle operations for Graph instances and Hypothesis Branches."""

from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any

import settings as Settings
from server.services.research_graph.branch.projection import (
    serialize_capability_resolution,
)
from server.services.research_graph.branch.repository import (
    branch_payload,
    load_instance_branch_row,
)
from server.services.research_graph.capability_resolution import (
    missing_required_capabilities,
    verify_capability_receipt,
)
from server.services.research_graph.protocol import GraphActivationBlocked
from server.services.research_graph.versions import (
    load_active_graph,
    load_graph,
)
from tools.data.sqlite.db import connect_sqlite


def create_graph_instance(
    *,
    graph_id: str,
    owner: str,
    product_group: str,
    workspace_id: str,
    capability_receipt: dict[str, Any],
    token_budget: int | None = None,
    shadow_graph_version: int | None = None,
    shadow_run_id: str = "",
) -> dict[str, Any]:
    # Compatibility only: Graph no longer owns or persists this value.
    del token_budget
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
        local_resolution = verify_capability_receipt(
            conn,
            owner_user_id=owner,
            receipt=capability_receipt,
            graph_id=graph_id,
            graph_version=int(active["version"]),
            node_id=entry_node,
            product_group=product_group,
            expected_mode=mode,
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
                instance_id, owner, graph_id, graph_version, product_group,
                workspace_id, mode, shadow_run_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                owner,
                graph_id,
                int(active["version"]),
                product_group,
                workspace_id,
                mode,
                shadow_run_id,
                now,
            ),
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
                branch_id, instance_id, label, current_node, status,
                current_capability_resolution_json,
                current_capability_resolution_hash,
                current_trial_plan_hash, created_at, updated_at
            ) VALUES (
                ?, ?, 'primary', ?, 'running', ?, ?, '', ?, ?
            )
            """,
            (
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
            "instance_id": instance_id,
            "label": "primary",
            "current_node": entry_node,
            "status": "running",
            "created_at": now,
            "updated_at": now,
        }
    return {
        "instance_id": instance_id,
        "owner": owner,
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
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        source = load_instance_branch_row(
            conn,
            instance_id=instance_id,
            branch_id=source_branch_id,
            owner=owner,
        )
        if source is None:
            raise KeyError("source branch not found")
        branch_id = uuid.uuid4().hex
        now = time.time()
        conn.execute(
            """
            INSERT INTO research_graph_branches (
                branch_id, instance_id, label, current_node, status,
                current_capability_resolution_json,
                current_capability_resolution_hash,
                current_trial_plan_hash, evidence_refs_json,
                omitted_evidence_count, latest_trace_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                branch_id,
                instance_id,
                str(label or "fork").strip(),
                str(source["current_node"]),
                str(source["current_capability_resolution_json"]),
                str(source["current_capability_resolution_hash"]),
                str(source["current_trial_plan_hash"]),
                str(source["evidence_refs_json"]),
                int(source["omitted_evidence_count"]),
                str(source["latest_trace_id"]),
                now,
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
