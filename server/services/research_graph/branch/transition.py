"""Atomic Graph branch transitions and bounded trace persistence."""

from __future__ import annotations

from copy import deepcopy
import time
import uuid
from typing import Any

import orjson

import settings as Settings
from server.services.research_graph.branch.projection import (
    normalize_capability_resolution,
    serialize_capability_resolution,
    validate_trial_plan_hash,
)
from server.services.research_graph.branch.repository import (
    branch_payload,
    load_current_branch_resolution,
    load_instance_branch_row,
)
from server.services.research_graph.capability_resolution import (
    missing_required_capabilities,
    verify_capability_receipt,
)
from server.services.research_graph.protocol import (
    assert_no_skill_identity,
    loads,
    merge_bounded_evidence_refs,
    serialize_bounded_trace_evidence,
)
from server.services.research_graph.versions import load_graph_from_conn
from tools.data.sqlite.db import connect_sqlite


def advance_graph_branch(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    edge_id: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise ValueError("transition evidence must be an object")
    persisted_evidence = deepcopy(evidence)
    persisted_evidence.pop("target_capability_receipt", None)
    persisted_evidence.pop("token_telemetry", None)
    assert_no_skill_identity(
        persisted_evidence,
        location="transition evidence",
    )
    # Reject obviously oversized payloads before opening a transaction. A
    # second check below includes the server-created receipt reference.
    serialize_bounded_trace_evidence(persisted_evidence)
    invocation_ids = evidence.get("agent_invocation_ids") or []
    if not isinstance(invocation_ids, list) or not all(
        isinstance(item, str) and item for item in invocation_ids
    ):
        raise ValueError("agent_invocation_ids must be an array")
    trial_plan_hash = validate_trial_plan_hash(
        evidence.get("trial_plan_hash")
    )
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        branch_row = load_instance_branch_row(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
        )
        if branch_row is None:
            raise KeyError("graph branch not found")
        branch = branch_payload(branch_row) or {}
        graph = load_graph_from_conn(
            conn,
            graph_id=str(branch_row["graph_id"]),
            version=int(branch_row["graph_version"]),
        ) or {}
        edge = next(
            (
                item
                for item in graph.get("edges") or []
                if str(item.get("edge_id") or "") == edge_id
            ),
            None,
        )
        if edge is None:
            raise KeyError("graph edge not found")
        edge_from = str(edge.get("from_node") or "")
        if edge_from not in {branch["current_node"], "*"}:
            raise ValueError(
                f"edge {edge_id} does not leave current node "
                f"{branch['current_node']}"
            )
        if branch["status"] == "paused" and edge.get("edge_type") != "recovery":
            raise ValueError("paused branch only accepts a recovery edge")
        failed_guards = [
            key
            for key, expected in (edge.get("guard") or {}).items()
            if evidence.get(key) != expected
        ]
        if failed_guards:
            raise ValueError(
                "transition guards not satisfied: " + ", ".join(failed_guards)
            )
        required_evidence = edge.get("required_evidence") or []
        evidence_refs = evidence.get("evidence_refs") or []
        if required_evidence and (
            not isinstance(evidence_refs, list) or not evidence_refs
        ):
            raise ValueError("transition requires evidence_refs")
        target_id = str(edge.get("to_node") or "")
        target = next(
            (
                item
                for item in graph.get("nodes") or []
                if str(item.get("node_id") or "") == target_id
            ),
            None,
        )
        if target is None:
            raise ValueError("transition target node is missing")
        supplied_receipt = evidence.get("target_capability_receipt")
        if supplied_receipt is not None:
            target_resolution = verify_capability_receipt(
                conn,
                owner_user_id=owner,
                receipt=supplied_receipt,
                graph_id=str(branch_row["graph_id"]),
                graph_version=int(branch_row["graph_version"]),
                node_id=target_id,
                product_group=str(branch_row["product_group"]),
                expected_mode=str(branch_row["mode"]),
            )
        elif target_id == branch["current_node"]:
            target_resolution = load_current_branch_resolution(branch_row)
        else:
            target_resolution = normalize_capability_resolution(
                {"node_id": target_id},
                node_id=target_id,
            )
        missing_capabilities = missing_required_capabilities(
            target,
            target_resolution or {},
        )
        if missing_capabilities and target.get("kind") != "capability_gap":
            raise ValueError(
                "target node has unresolved capabilities: "
                + ", ".join(missing_capabilities)
                + "; use the declared capability-gap edge"
            )
        status = (
            "paused"
            if target.get("kind") == "capability_gap"
            or target_id == "code_improvement_required"
            else "running"
        )
        trace_evidence = deepcopy(persisted_evidence)
        if supplied_receipt is not None:
            trace_evidence["target_capability_receipt_ref"] = (
                f"branch-resolution:{instance_id}:{branch_id}"
            )
        trace_evidence_json = serialize_bounded_trace_evidence(trace_evidence)
        bounded_evidence_refs, omitted_evidence_count = (
            merge_bounded_evidence_refs(
                loads(branch_row["evidence_refs_json"]) or [],
                int(branch_row["omitted_evidence_count"]),
                trace_evidence.get("evidence_refs"),
            )
        )
        _, resolution_json, resolution_hash = (
            serialize_capability_resolution(
                target_resolution,
                node_id=target_id,
            )
        )
        projected_trial_plan_hash = (
            trial_plan_hash
            if "trial_plan_hash" in evidence
            else str(branch_row["current_trial_plan_hash"])
        )
        trace_id = uuid.uuid4().hex
        now = time.time()
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node=?, status=?,
                current_capability_resolution_json=?,
                current_capability_resolution_hash=?,
                current_trial_plan_hash=?,
                evidence_refs_json=?, omitted_evidence_count=?,
                latest_trace_id=?, updated_at=?
            WHERE branch_id=? AND instance_id=?
            """,
            (
                target_id,
                status,
                resolution_json,
                resolution_hash,
                projected_trial_plan_hash,
                orjson.dumps(bounded_evidence_refs).decode(),
                omitted_evidence_count,
                trace_id,
                now,
                branch_id,
                instance_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                instance_id,
                branch_id,
                edge_id,
                branch["current_node"],
                target_id,
                trace_evidence_json,
                "{}",
                owner,
                now,
            ),
        )
    return {
        "branch_id": branch_id,
        "instance_id": instance_id,
        "label": branch["label"],
        "current_node": target_id,
        "status": status,
        "created_at": branch["created_at"],
        "updated_at": now,
    }
