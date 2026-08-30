"""Deterministic edge readiness in one compact Agent packet."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import orjson

from server.services.research_graph.branch.context import _build_local_state
from server.services.research_graph.branch import server_actions


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
    cycle = context["research_cycle"]
    obligations_by_id = {}
    for item in [
        *(cycle.get("obligations") or []),
        *(cycle.get("open_obligations") or []),
    ]:
        if not isinstance(item, dict) or not item.get("obligation_id"):
            continue
        obligations_by_id[str(item["obligation_id"])] = (
            _compact_obligation(item)
        )
    obligations = list(obligations_by_id.values())
    entry_requirements = deepcopy(context.get("entry_requirements") or [])
    packet: dict[str, Any] = {
        "graph": context["graph"],
        "branch": deepcopy(context["branch"]),
        "node": deepcopy(context["node"]),
        "report_container": deepcopy(context["report_container"]),
        "human_gate_override": deepcopy(
            context.get("human_gate_override") or {}
        ),
        **({
            "capability_detour": deepcopy(context["capability_detour"]),
        } if context.get("capability_detour") else {}),
        "context_ref": "sha256:" + hashlib.sha256(
            orjson.dumps(context, option=orjson.OPT_SORT_KEYS)
        ).hexdigest(),
        "checkpoint_ref": str(context.get("history_cursor") or ""),
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
        # Edge readiness and report requirements are authoritative state. The
        # client CLI chooses the next action from its downloaded Graph and
        # local facts; the Manager must not prescribe an ordered action list.
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
        "server_decides_next": False,
        "running_backend_jobs_action": "continue",
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
                "factortester research graphs requirement-detail "
                "<instance> <branch> <requirement-id>"
            ),
        }
        packet["node_report_requirement_refs"] = list(
            context.get("node_report_requirement_refs") or []
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
    context, edges = _build_local_state(
        instance_id=instance_id,
        branch_id=branch_id,
        owner=owner,
        report_edge_id=edge_id,
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
        "target_capabilities": deepcopy(
            candidate.get("target_capabilities") or {
                "node_id": str(candidate.get("to_node") or ""),
                "required": [],
                "resolution_required": False,
            }
        ),
        "state_ref": context.get("history_cursor"),
    }
    value["server_decides_next"] = False
    return value


def _compact_obligation(item: dict[str, Any]) -> dict[str, Any]:
    """Keep routing semantics; load Claim links and criteria by detail_ref."""

    return {
        key: deepcopy(item.get(key))
        for key in (
            "obligation_id",
            "claim_ids",
            "scope",
            "coverage_scope",
            "claim_scopes",
            "contract_hash",
            "methodology_hash",
            "materiality",
            "status",
            "question_summary",
            "requirement_refs",
            "detail_ref",
        )
        if key in item
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
        "target_required_capability_ids": [
            str(item.get("capability_id") or "")
            for item in (
                (edge.get("target_capabilities") or {}).get("required")
                or []
            )
            if isinstance(item, dict) and item.get("capability_id")
        ],
    }
    if "report_requirement_refs" in edge:
        value["report_requirement_refs"] = list(
            edge.get("report_requirement_refs") or []
        )
    if "obligation_requirements" in edge:
        value["obligation_requirements"] = deepcopy(
            edge.get("obligation_requirements") or []
        )
    action_contract = server_actions.contract_for_edge(edge)
    if action_contract is not None:
        value["action_contract"] = action_contract
    return value
