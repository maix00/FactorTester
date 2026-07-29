"""Deterministic edge readiness in one compact Agent packet."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import orjson

from server.services.research_graph.branch.context import _build_local_state
from server.services.research_graph.branch.report_requirements import (
    compact_report_requirements,
)
from server.services.research_graph.branch.next_actions import (
    compact_next_actions,
    edge_next_actions,
)
from server.services.research_graph.branch import server_actions


COMPACT_NEXT_TARGET_BYTES = 6000


def _with_next_bytes(packet: dict[str, Any]) -> int:
    packet["next_bytes"] = 0
    for _ in range(3):
        packet["next_bytes"] = len(orjson.dumps(packet))
    return len(orjson.dumps(packet))


def _compact_next_for_budget(packet: dict[str, Any]) -> dict[str, Any]:
    """Preserve routable choices while moving verbose contracts to detail reads."""
    value = deepcopy(packet)
    value["capabilities"] = [
        {
            "capability_id": str(item.get("capability_id") or ""),
            "status": str(item.get("status") or ""),
            "detail_ref": (
                "capability-resolution:"
                f"{item.get('capability_id') or ''}"
            ),
        }
        for item in value.get("capabilities") or []
        if isinstance(item, dict)
    ]
    value["candidate_edges"] = [
        {
            key: deepcopy(item.get(key))
            for key in (
                "edge_id",
                "to_node",
                "edge_type",
                "risk_level",
                "readiness",
                "blockers",
            )
            if key in item
        } | {
            "detail_ref": (
                "graph-edge:"
                f"{item.get('edge_id') or ''}"
            ),
            **({"requires_server_action": True}
               if item.get("action_contract") else {}),
        }
        for item in value.get("candidate_edges") or []
        if isinstance(item, dict)
    ]
    frontier = value.get("candidate_trial_frontier") or {}
    value["candidate_trial_frontier"] = {
        "current_trial_plan_hash": frontier.get("current_trial_plan_hash"),
        "unassessed_obligation_count": frontier.get(
            "unassessed_obligation_count", 0
        ),
    }
    value.pop("entry_resolution", None)
    value["report_requirements"] = _minimal_next_report_requirements(
        value.get("report_requirements")
    )
    value["entry_requirements"] = [
        {
            key: deepcopy(item.get(key))
            for key in ("requirement_id",)
            if key in item
        }
        for item in value.get("entry_requirements") or []
        if isinstance(item, dict)
    ]
    value["next_actions"] = compact_next_actions(
        value.get("next_actions")
    )
    if "entry_requirement_policy" in value:
        value["entry_requirement_policy"] = {
            "detail_ref": "graph-entry-requirements",
        }
    value.pop("node_report_requirement_refs", None)
    value["packet_compaction"] = {
        "mode": "lazy_edge_contracts",
        "detail_command": (
            "factortester research step inspect <instance> <branch>"
        ),
    }
    return value


def _minimal_next_report_requirements(value: Any) -> dict[str, Any]:
    """Keep current-node status; edge detail is available from ``edge info``."""
    if not isinstance(value, dict):
        return {
            "enforcement": "optional",
            "current_node": {},
            "candidate_edges": {},
        }

    def rows(items: Any) -> list[dict[str, Any]]:
        return [
            {
                key: item[key]
                for key in ("report_requirement_id", "status")
                if key in item
            }
            for item in items or []
            if isinstance(item, dict)
        ]

    current = value.get("current_node") or {}
    return {
        "enforcement": str(value.get("enforcement") or "optional"),
        "current_node": {
            key: rows(items)
            for key, items in current.items()
            if key in {"on_entry", "on_exit"}
        },
        "candidate_edges": {},
    }


def build_graph_branch_next(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> dict[str, Any]:
    """Return current semantics without a full Graph, catalog, or history."""
    context, edges, ceiling_bytes = _build_local_state(
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
    obligations = [
        _compact_obligation(item)
        for item in cycle.get("open_obligations") or []
        if isinstance(item, dict)
    ]
    entry_requirements = deepcopy(context.get("entry_requirements") or [])
    packet: dict[str, Any] = {
        "graph": context["graph"],
        "branch": deepcopy(context["branch"]),
        "node": deepcopy(context["node"]),
        "report_container": deepcopy(context["report_container"]),
        **({
            "capability_detour": deepcopy(context["capability_detour"]),
        } if context.get("capability_detour") else {}),
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
        "report_requirements": deepcopy(
            context.get("report_requirements") or {}
        ),
        "next_actions": deepcopy(context.get("next_actions") or []),
        "candidate_trial_frontier": {
            "current_trial_plan_hash": cycle.get("trial_plan_hash"),
            "trial_stage": deepcopy(context.get("trial_stage")),
            "candidate_plan_refs": [],
            "unassessed_obligation_count": len(obligations),
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
            entry_requirements
            or undetermined_ids
            or non_blocked_count > 1
        ),
        "running_backend_jobs_action": "continue",
        "next_bytes": 0,
    }
    if context.get("budget_profile_ref"):
        packet["budget_profile"] = {
            "profile_ref": str(context["budget_profile_ref"]),
            "profile_hash": str(context["budget_profile_hash"]),
            "ceiling_bytes": ceiling_bytes,
        }
    if "entry_requirements" in context:
        packet["entry_requirements"] = entry_requirements
        if "entry_resolution" in context:
            packet["entry_resolution"] = deepcopy(
                context["entry_resolution"]
            )
        packet["entry_requirement_policy"] = {
            "required_dimensions": [
                "applicability",
                "coverage",
                "resolution",
                "entry_effect",
            ],
            "agent_action": (
                "submit_one_orthogonal_assessment_per_unresolved_"
                "requirement_before_leaving_current_node"
            ),
            "detail_command": (
                "factortester research-graph requirement-detail "
                "<instance> <branch> <requirement-id>"
            ),
        }
        packet["node_report_requirement_refs"] = list(
            context.get("node_report_requirement_refs") or []
        )
    serialized_bytes = _with_next_bytes(packet)
    if serialized_bytes > min(ceiling_bytes, COMPACT_NEXT_TARGET_BYTES):
        packet = _compact_next_for_budget(packet)
        serialized_bytes = _with_next_bytes(packet)
    if serialized_bytes > ceiling_bytes:
        raise ValueError(
            "bounded next packet exceeds "
            f"{ceiling_bytes} bytes: {serialized_bytes}; "
            "request the detail packet before continuing"
        )
    return packet


def build_graph_branch_edge_info(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    edge_id: str,
) -> dict[str, Any]:
    """Return one candidate Edge and its exact report requirements."""
    context, edges, ceiling_bytes = _build_local_state(
        instance_id=instance_id,
        branch_id=branch_id,
        owner=owner,
    )
    candidate = next(
        (
            item for item in edges
            if str(item.get("edge_id") or "") == edge_id
        ),
        None,
    )
    if candidate is None:
        raise KeyError("edge is not available from the current node")
    open_gap_ids = _capability_ids(context.get("open_gaps"))
    undetermined_ids = _capability_ids(
        context.get("undetermined_conditions")
    )
    value = {
        "graph": context["graph"],
        "branch": deepcopy(context["branch"]),
        "node": deepcopy(context["node"]),
        "report_container": deepcopy(context["report_container"]),
        **({
            "capability_detour": deepcopy(context["capability_detour"]),
        } if context.get("capability_detour") else {}),
        "edge": _edge_candidate(
            candidate,
            open_gap_ids=open_gap_ids,
            undetermined_ids=undetermined_ids,
        ),
        "report_requirements": deepcopy(
            (context.get("report_requirements") or {})
            .get("candidate_edges", {})
            .get(edge_id, [])
        ),
        "state_ref": context.get("history_cursor"),
        "next_bytes": 0,
    }
    report_contract = context.get("report_requirements") or {}
    value["next_actions"] = edge_next_actions(
        instance_id=instance_id,
        branch_id=branch_id,
        edge_id=edge_id,
        requirements=value["report_requirements"],
        enforcement=str(report_contract.get("enforcement") or "optional"),
    )
    serialized = _with_next_bytes(value)
    if serialized > ceiling_bytes:
        value["report_requirements"] = compact_report_requirements({
            "enforcement": (
                context.get("report_requirements") or {}
            ).get("enforcement"),
            "current_node": {"on_entry": [], "on_exit": []},
            "candidate_edges": {
                edge_id: value["report_requirements"],
            },
        }).get("candidate_edges", {}).get(edge_id, [])
        serialized = _with_next_bytes(value)
    if serialized > ceiling_bytes:
        raise ValueError(
            f"bounded edge info exceeds {ceiling_bytes} bytes: {serialized}"
        )
    return value


def _compact_obligation(item: dict[str, Any]) -> dict[str, Any]:
    """Keep routing semantics; load Claim links and criteria by detail_ref."""

    return {
        key: deepcopy(item.get(key))
        for key in (
            "obligation_id",
            "materiality",
            "status",
            "question_summary",
            "detail_ref",
        )
    }


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
    value = {
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
    if "report_requirement_refs" in edge:
        value["report_requirement_refs"] = list(
            edge.get("report_requirement_refs") or []
        )
    action_contract = server_actions.contract_for_edge(edge)
    if action_contract is not None:
        value["action_contract"] = action_contract
    return value
