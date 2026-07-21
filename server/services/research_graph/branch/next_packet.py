"""Deterministic edge readiness in one compact Agent packet."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import orjson

from server.services.research_graph.branch.context import _build_local_state
from server.services.research_graph.protocol import MAX_AGENT_PACKET_BYTES


def build_graph_branch_next(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> dict[str, Any]:
    """Return current semantics without a full Graph, catalog, or history."""
    context, edges = _build_local_state(
        instance_id=instance_id,
        branch_id=branch_id,
        owner=owner,
    )
    open_gap_ids = _capability_ids(context.get("open_gaps"))
    undetermined_ids = _capability_ids(
        context.get("undetermined_conditions")
    )
    candidates = [
        _edge_candidate(
            edge,
            open_gap_ids=open_gap_ids,
            undetermined_ids=undetermined_ids,
        )
        for edge in edges
    ]
    ready_l1 = [
        item["edge_id"]
        for item in candidates
        if item["readiness"] == "ready"
        and item["risk_level"] == "L1"
    ]
    non_blocked_count = sum(
        item["readiness"] != "blocked" for item in candidates
    )
    cycle = context["research_cycle"]
    obligations = deepcopy(cycle.get("open_obligations") or [])
    packet = {
        "graph": context["graph"],
        "branch": deepcopy(context["branch"]),
        "node": deepcopy(context["node"]),
        "context_ref": "sha256:" + hashlib.sha256(
            orjson.dumps(context, option=orjson.OPT_SORT_KEYS)
        ).hexdigest(),
        "capabilities": _compact_capabilities(context),
        "unresolved_capability_conditions": [
            {
                "capability_id": str(item.get("capability_id") or ""),
                "explanation": str(item.get("explanation") or ""),
            }
            for item in context.get("undetermined_conditions") or []
            if isinstance(item, dict)
        ],
        "current_obligations": obligations,
        "candidate_trial_frontier": {
            "current_trial_plan_hash": cycle.get("trial_plan_hash"),
            "trial_stage": deepcopy(context.get("trial_stage")),
            "candidate_plan_refs": [],
            "unassessed_obligation_ids": [
                item["obligation_id"] for item in obligations
            ],
        },
        "changed_refs": list(dict.fromkeys([
            *context.get("evidence_refs", []),
            context.get("history_cursor"),
        ])) if context.get("history_cursor") else list(
            context.get("evidence_refs", [])
        ),
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


def _capability_ids(value: Any) -> list[str]:
    return sorted({
        str(item.get("capability_id") or "")
        for item in value or []
        if isinstance(item, dict)
    })


def _compact_capabilities(context: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in [
        *context.get("required_capabilities", []),
        *context.get("triggered_capabilities", []),
    ]:
        semantic = item.get("binding") or item.get("gap") or {}
        row = {
            "capability_id": item.get("capability_id"),
            "capability_description": semantic.get(
                "capability_description"
            ),
            "descriptor_hash": semantic.get("descriptor_hash"),
            "status": "gap" if item.get("gap") else "bound",
        }
        if item.get("gap"):
            row["reason"] = semantic.get("reason")
        if row not in rows:
            rows.append(row)
    return rows


def _edge_candidate(
    edge: dict[str, Any],
    *,
    open_gap_ids: list[str],
    undetermined_ids: list[str],
) -> dict[str, Any]:
    guard_fields = sorted((edge.get("guard") or {}).keys())
    legacy_required = list(edge.get("required_evidence") or [])
    required_research_evidence = list(
        edge.get("required_research_evidence") or []
    )
    required_transition_facts = list(
        edge.get("required_transition_facts") or []
    )
    if (
        legacy_required
        and not required_research_evidence
        and not required_transition_facts
    ):
        required_transition_facts = legacy_required
    blockers = []
    if open_gap_ids and edge.get("edge_type") != "failure":
        blockers.append({
            "code": "open_capability_gaps",
            "capability_ids": open_gap_ids,
        })
    if undetermined_ids and edge.get("edge_type") != "failure":
        blockers.append({
            "code": "semantic_conditions_undetermined",
            "capability_ids": undetermined_ids,
        })
    readiness = (
        "blocked"
        if blockers
        else "requires_evidence"
        if (
            guard_fields
            or required_research_evidence
            or required_transition_facts
        )
        else "ready"
    )
    risk_level = str(edge.get("risk_level") or "L1")
    review_requirement = {
        "L1": "none",
        "L2": "self_check; one_reviewer_only_on_trigger",
        "L3": "one_specialist",
        "L4": "proposer_plus_independent_reviewer",
    }.get(risk_level, "invalid")
    return {
        "edge_id": str(edge.get("edge_id") or ""),
        "to_node": str(edge.get("to_node") or ""),
        "edge_type": str(edge.get("edge_type") or ""),
        "risk_level": risk_level,
        "readiness": readiness,
        "required_guard_fields": guard_fields,
        "required_research_evidence": required_research_evidence,
        "required_transition_facts": required_transition_facts,
        "blockers": blockers,
        "review_requirement": review_requirement,
    }
