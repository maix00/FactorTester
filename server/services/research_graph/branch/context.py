"""Bounded local Agent packets for the current Hypothesis Branch."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import orjson

import settings as Settings
from server.services.research_graph.branch.repository import (
    branch_payload,
    load_current_branch_resolution,
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.branch.research_cycle import (
    agent_cycle_summary,
    checkpoint_from_branch_row,
)
from server.services.research_graph.protocol import (
    MAX_AGENT_PACKET_BYTES,
    loads,
)
from server.services.research_graph.versions import load_graph_from_conn
from tools.data.sqlite.db import connect_sqlite


def _build_local_state(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build compact current state plus internal candidate edge definitions."""
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        branch_row = load_instance_branch_with_latest_trace(
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
        node = next(
            (
                item
                for item in graph.get("nodes") or []
                if str(item.get("node_id") or "") == branch["current_node"]
            ),
            None,
        )
        if node is None:
            raise ValueError("current graph node is missing")
        available_edges = [
            {
                "edge_id": str(edge.get("edge_id") or ""),
                "to_node": str(edge.get("to_node") or ""),
                "edge_type": str(edge.get("edge_type") or ""),
                "risk_level": str(edge.get("risk_level") or ""),
                "guard": deepcopy(edge.get("guard") or {}),
                "required_evidence": deepcopy(
                    edge.get("required_evidence") or []
                ),
            }
            for edge in graph.get("edges") or []
            if str(edge.get("from_node") or "") in {
                branch["current_node"],
                "*",
            }
            and (
                branch["status"] != "paused"
                or edge.get("edge_type") == "recovery"
            )
        ]
        resolution = load_current_branch_resolution(branch_row)
        binding_by_id = {
            str(item.get("capability_id") or ""): item
            for key in ("bindings", "triggered_conditional_bindings")
            for item in resolution.get(key) or []
            if isinstance(item, dict)
        }
        gap_by_id = {
            str(item.get("capability_id") or ""): item
            for key in ("gaps", "triggered_conditional_gaps")
            for item in resolution.get(key) or []
            if isinstance(item, dict)
        }
        required_capabilities = [
            {
                "capability_id": capability_id,
                "binding": deepcopy(binding_by_id.get(capability_id)),
                "gap": deepcopy(gap_by_id.get(capability_id)),
            }
            for capability_id in node.get("required_capabilities") or []
        ]
        evidence_refs = loads(branch_row["evidence_refs_json"]) or []
        omitted_evidence_count = int(
            branch_row["omitted_evidence_count"]
        )
        latest_trace_id = str(branch_row["latest_trace_id"])
        product_group = str(branch_row["product_group"])
        workspace_id = str(branch_row["workspace_id"])
        resolution_hash = str(
            branch_row["current_capability_resolution_hash"]
        )
        trial_plan_hash = (
            str(branch_row["current_trial_plan_hash"]) or None
        )
        research_cycle = agent_cycle_summary(
            checkpoint_from_branch_row(branch_row)
        )
    triggered_gap_ids = {
        str(item.get("capability_id") or "")
        for item in resolution.get("triggered_conditional_gaps") or []
        if isinstance(item, dict)
    }
    current_ids = (
        set(node.get("required_capabilities") or [])
        | triggered_gap_ids
    )
    open_gaps = [
        deepcopy(gap)
        for capability_id, gap in gap_by_id.items()
        if capability_id in current_ids or node.get("kind") == "capability_gap"
    ]
    triggered_capabilities = [
        {
            "capability_id": capability_id,
            "binding": deepcopy(binding_by_id.get(capability_id)),
            "gap": deepcopy(gap_by_id.get(capability_id)),
        }
        for capability_id in sorted({
            str(item.get("capability_id") or "")
            for key in (
                "triggered_conditional_bindings",
                "triggered_conditional_gaps",
            )
            for item in resolution.get(key) or []
            if isinstance(item, dict)
        })
    ]
    context = {
        "graph": f"{graph['graph_id']}@v{graph['version']}",
        "branch": {
            "instance_id": instance_id,
            "branch_id": branch_id,
            "status": branch["status"],
            "product_group": product_group,
            "workspace_id": workspace_id,
            "capability_resolution_hash": resolution_hash,
            "trial_plan_hash": trial_plan_hash,
        },
        "node": {
            "node_id": branch["current_node"],
            "kind": str(node.get("kind") or ""),
            "purpose": str(node.get("purpose") or ""),
        },
        "required_capabilities": required_capabilities,
        "triggered_capabilities": triggered_capabilities,
        "undetermined_conditions": deepcopy(
            resolution.get("undetermined_conditions") or []
        ),
        "evidence_refs": evidence_refs,
        "omitted_evidence_count": omitted_evidence_count,
        "history_cursor": (
            f"trace:{latest_trace_id}" if latest_trace_id else None
        ),
        "research_cycle": research_cycle,
        "open_gaps": open_gaps,
        "skill_policy": {
            "match_on": "capability_description",
            "agent_action": (
                "reuse_matching_runtime_skill_else_load_after_trigger_"
                "and_approval"
            ),
            "persist": "description_and_descriptor_hash_only",
        },
        "review_policy": {
            "L1": "deterministic_only",
            "L2": (
                "zero_by_default; one_reviewer_only_for_conflict_"
                "semantic_uncertainty_or_low_confidence"
            ),
            "L3": "exactly_one_relevant_specialist_reviewer",
            "L4": (
                "one_proposer_plus_one_independent_reviewer; "
                "third_only_on_disagreement; grill_only_change_diff"
            ),
        },
    }
    context["context_bytes"] = 0
    for _ in range(3):
        context["context_bytes"] = len(orjson.dumps(context))
    serialized_bytes = len(orjson.dumps(context))
    if serialized_bytes > MAX_AGENT_PACKET_BYTES:
        raise ValueError(
            "bounded context exceeds "
            f"{MAX_AGENT_PACKET_BYTES} bytes: {serialized_bytes}"
        )
    return context, available_edges


def build_graph_branch_context(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> dict[str, Any]:
    """Return current state without edge-selection instructions."""
    context, _ = _build_local_state(
        instance_id=instance_id,
        branch_id=branch_id,
        owner=owner,
    )
    return context


def build_graph_branch_next(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> dict[str, Any]:
    """Return deterministic edge readiness and only necessary Agent triggers."""
    context, edges = _build_local_state(
        instance_id=instance_id,
        branch_id=branch_id,
        owner=owner,
    )
    open_gap_ids = sorted({
        str(item.get("capability_id") or "")
        for item in context.get("open_gaps") or []
        if isinstance(item, dict)
    })
    undetermined_ids = sorted({
        str(item.get("capability_id") or "")
        for item in context.get("undetermined_conditions") or []
        if isinstance(item, dict)
    })
    candidates = []
    for edge in edges:
        guard_fields = sorted((edge.get("guard") or {}).keys())
        required_evidence = list(edge.get("required_evidence") or [])
        blockers = []
        if open_gap_ids and edge.get("edge_type") != "failure":
            blockers.append({
                "code": "open_capability_gaps",
                "capability_ids": open_gap_ids,
            })
        if undetermined_ids:
            blockers.append({
                "code": "semantic_conditions_undetermined",
                "capability_ids": undetermined_ids,
            })
        if blockers:
            readiness = "blocked"
        elif guard_fields or required_evidence:
            readiness = "requires_evidence"
        else:
            readiness = "ready"
        risk_level = str(edge.get("risk_level") or "L1")
        review_requirement = {
            "L1": "none",
            "L2": "self_check; one_reviewer_only_on_trigger",
            "L3": "one_specialist",
            "L4": "proposer_plus_independent_reviewer",
        }.get(risk_level, "invalid")
        candidates.append({
            "edge_id": str(edge.get("edge_id") or ""),
            "to_node": str(edge.get("to_node") or ""),
            "edge_type": str(edge.get("edge_type") or ""),
            "risk_level": risk_level,
            "readiness": readiness,
            "required_guard_fields": guard_fields,
            "required_evidence": required_evidence,
            "blockers": blockers,
            "review_requirement": review_requirement,
        })
    ready_l1 = [
        item["edge_id"]
        for item in candidates
        if item["readiness"] == "ready"
        and item["risk_level"] == "L1"
    ]
    non_blocked_count = len([
        item for item in candidates if item["readiness"] != "blocked"
    ])
    packet = {
        "graph": context["graph"],
        "branch": deepcopy(context["branch"]),
        "node": deepcopy(context["node"]),
        "context_ref": "sha256:" + hashlib.sha256(
            orjson.dumps(context, option=orjson.OPT_SORT_KEYS)
        ).hexdigest(),
        "candidate_edges": candidates,
        "recommended_edge_ids": (
            ready_l1 if len(ready_l1) == 1 else []
        ),
        "requires_agent_judgment": bool(
            undetermined_ids or non_blocked_count > 1
        ),
        "running_backend_jobs_action": "continue",
        "next_bytes": 0,
    }
    for _ in range(3):
        packet["next_bytes"] = len(orjson.dumps(packet))
    serialized_bytes = len(orjson.dumps(packet))
    if serialized_bytes > MAX_AGENT_PACKET_BYTES:
        raise ValueError(
            "bounded next packet exceeds "
            f"{MAX_AGENT_PACKET_BYTES} bytes: {serialized_bytes}"
        )
    return packet
