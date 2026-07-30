"""Bounded local Agent packets for the current Hypothesis Branch."""

from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from typing import Any

import settings as Settings
from server.services.research_graph.branch.repository import (
    branch_payload,
    load_current_branch_resolution,
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.branch.capability_detour import (
    contract_enabled as capability_detour_enabled,
    filter_available_edges,
    load_or_reconstruct,
    requires_state as capability_detour_requires_state,
    report_container as capability_report_container,
)
from server.services.research_graph.branch.entry_requirements import (
    compact_entry_requirements,
)
from server.services.research_graph.branch.report_requirements import (
    compact_report_requirements,
    minimal_report_requirements,
    node_report_requirements,
)
from server.services.research_graph.branch.next_actions import (
    compact_next_actions,
    node_next_actions,
)
from server.services.research_graph.branch.entry_resolution import (
    active_entry_requirement_ids,
    compact_entry_resolution_frame,
)
from server.services.research_graph.branch.context_budget import (
    fit_compacted_context,
    with_context_bytes,
)
from server.services.research_graph.branch.research_cycle import (
    agent_cycle_summary,
    checkpoint_from_branch_row,
)
from server.services.research_graph.protocol import (
    loads,
)
from server.services.research_graph.packet_budget import graph_packet_budget
from server.services.research_graph.versions import load_graph_from_conn
from server.services.research_graph.trial_plan.stage_projection import (
    agent_trial_stage_summary,
)
from tools.data.sqlite.db import connect_sqlite


MAX_CONTEXT_EVIDENCE_REFS = 6
MAX_CONTEXT_OBLIGATION_SUMMARY_BYTES = 72
COMPACT_CONTEXT_TARGET_BYTES = 6000


def _bounded_text(value: Any, *, max_bytes: int) -> str:
    encoded = str(value or "").encode()
    if len(encoded) <= max_bytes:
        return str(value or "")
    return encoded[: max_bytes - 3].decode(errors="ignore") + "..."


def _compact_research_cycle(value: dict[str, Any]) -> dict[str, Any]:
    """Keep routable aliases in-context; full bodies remain detail-ref reads."""
    result = deepcopy(value)
    obligations = [
        {
            "obligation_id": str(item.get("obligation_id") or ""),
            "materiality": str(item.get("materiality") or ""),
            "status": str(item.get("status") or ""),
            "question_summary": _bounded_text(
                item.get("question_summary"),
                max_bytes=MAX_CONTEXT_OBLIGATION_SUMMARY_BYTES,
            ),
            "detail_ref": str(item.get("detail_ref") or ""),
        }
        for item in value.get("open_obligations") or []
        if isinstance(item, dict)
    ]
    result["open_obligations"] = obligations
    result["open_obligation_count"] = len(obligations)
    return result


def _compact_context_for_budget(context: dict[str, Any]) -> dict[str, Any]:
    """Keep routing identities when a schema-v2 packet needs lazy details.

    The full capability and requirement contracts remain available through
    their detail reads.  This path is deliberately conditional: ordinary,
    already-small packets retain their richer explanatory projection.
    """
    value = deepcopy(context)
    for field in ("required_capabilities", "triggered_capabilities"):
        value[field] = [
            {
                "capability_id": str(item.get("capability_id") or ""),
                "status": "gap" if item.get("gap") else "bound",
                "detail_ref": (
                    "capability-resolution:"
                    f"{item.get('capability_id') or ''}"
                ),
            }
            for item in value.get(field) or []
            if isinstance(item, dict)
        ]
    value["open_gaps"] = [
        {
            "capability_id": str(item.get("capability_id") or ""),
            "detail_ref": (
                "capability-resolution:"
                f"{item.get('capability_id') or ''}"
            ),
        }
        for item in value.get("open_gaps") or []
        if isinstance(item, dict)
    ]
    value["undetermined_conditions"] = [
        {
            "capability_id": str(item.get("capability_id") or ""),
            "explanation": _bounded_text(
                item.get("explanation"), max_bytes=96
            ),
        }
        for item in value.get("undetermined_conditions") or []
        if isinstance(item, dict)
    ]
    value["entry_requirements"] = [
        {
            key: deepcopy(item.get(key))
            for key in (
                "requirement_id",
                "detail_ref",
            )
        }
        for item in value.get("entry_requirements") or []
        if isinstance(item, dict)
    ]
    value["research_cycle"] = _compact_cycle_for_budget(
        value.get("research_cycle")
    )
    value["report_requirements"] = minimal_report_requirements(
        value.get("report_requirements")
    )
    value["next_actions"] = [
        {
            key: deepcopy(item.get(key))
            for key in (
                "action_id", "blocking", "command", "validate_command",
                "then", "edge_ids", "requirement_ids",
            )
            if key in item
        }
        for item in value.get("next_actions") or []
        if isinstance(item, dict)
    ]
    # The report contract already carries the active node's requirement IDs;
    # retaining this second graph-level list duplicates the same payload at
    # the byte ceiling. Keep a count so the agent can still detect that
    # additional node-level bindings exist and fetch the detail packet.
    node_report_refs = value.pop("node_report_requirement_refs", [])
    if isinstance(node_report_refs, list) and node_report_refs:
        value["node_report_requirement_count"] = len(node_report_refs)
    # These stable policies are available from the node detail read.  The
    # bounded resume packet prioritizes the action and gate state instead of
    # repeating two explanatory policy objects.
    value.pop("skill_policy", None)
    value.pop("review_policy", None)
    value["packet_compaction"] = {
        "mode": "lazy_contract_details",
        "detail_command": (
            "factortester research step inspect "
            "<instance-id> <branch-id> --output <file>"
        ),
    }
    return value


def _compact_cycle_for_budget(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = deepcopy(value)
    result["open_obligations"] = [
        {
            **{
                key: item.get(key)
                for key in (
                    "obligation_id", "materiality", "status",
                )
                if key in item
            },
            "question_summary": _bounded_text(
                item.get("question_summary"), max_bytes=12,
            ),
            "detail_ref": _bounded_text(item.get("detail_ref"), max_bytes=40),
        }
        for item in value.get("open_obligations") or []
        if isinstance(item, dict)
    ]
    result["open_obligation_count"] = len(result["open_obligations"])
    return result


def _build_local_state(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    """Build compact current state plus internal candidate edge definitions."""
    with closing(connect_sqlite(Settings.CACHE_DB_PATH)) as conn:
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
        latest_trace_evidence = loads(
            branch_row["latest_trace_evidence_json"]
        ) or {}
        schema_version = int(graph.get("schema_version") or 1)
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
        capability_detour = (
            load_or_reconstruct(
                conn,
                instance_id=instance_id,
                branch_id=branch_id,
            )
            if (
                capability_detour_enabled(graph.get("edges") or [])
                and capability_detour_requires_state(branch["current_node"])
            )
            else None
        )
        if capability_detour is not None:
            capability_detour = deepcopy(capability_detour)
            capability_detour["latest_trace_id"] = str(
                branch_row["latest_trace_id"] or ""
            )
        candidate_edges = filter_available_edges(
            graph.get("edges") or [],
            current_node=branch["current_node"],
            state=capability_detour,
        )
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
                "required_research_evidence": deepcopy(
                    edge.get("required_research_evidence") or []
                ),
                "required_transition_facts": deepcopy(
                    edge.get("required_transition_facts") or []
                ),
                **({
                    "report_requirement_refs": deepcopy(
                        edge.get("report_requirement_refs") or []
                    ),
                } if schema_version >= 2 else {}),
            }
            for edge in candidate_edges
            if (
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
        stored_evidence_refs = loads(branch_row["evidence_refs_json"]) or []
        evidence_refs = stored_evidence_refs[-MAX_CONTEXT_EVIDENCE_REFS:]
        omitted_evidence_count = (
            int(branch_row["omitted_evidence_count"])
            + max(0, len(stored_evidence_refs) - len(evidence_refs))
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
        trial_stage = agent_trial_stage_summary(
            loads(branch_row["trial_stage_projection_json"]) or {}
        )
        cycle_checkpoint = checkpoint_from_branch_row(branch_row)
        research_cycle = _compact_research_cycle(
            agent_cycle_summary(cycle_checkpoint)
        )
        entry_resolution_frame = loads(
            branch_row["entry_resolution_frame_json"]
        ) or {}
        active_entry_ids = active_entry_requirement_ids(
            frame=entry_resolution_frame,
            current_node=branch["current_node"],
        )
        entry_requirements = (
            compact_entry_requirements(
                graph=graph,
                node=node,
                checkpoint=cycle_checkpoint,
                active_requirement_ids=active_entry_ids,
            )
            if schema_version >= 2
            else []
        )
        report_requirements = (
            node_report_requirements(
                graph=graph,
                node=node,
                edges=available_edges,
                report_submission=latest_trace_evidence.get(
                    "report_submission"
                ),
            )
            if schema_version >= 2 else {}
        )
        next_actions = (
            node_next_actions(
                instance_id=instance_id,
                branch_id=branch_id,
                context={"report_requirements": report_requirements},
                edges=available_edges,
            )
            if schema_version >= 2 else []
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
            "work_package_id": str(
                branch_row["work_package_id"] or instance_id
            ),
            "current_owner_profile_ref": str(
                branch_row["current_owner_profile_ref"] or ""
            ),
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
        "report_container": capability_report_container(
            node_id=branch["current_node"],
            state=capability_detour,
        ),
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
        "trial_stage": trial_stage,
        "open_gaps": open_gaps,
        **({
            "capability_detour": deepcopy(capability_detour),
        } if capability_detour is not None else {}),
        "skill_policy": {
            "policy_ref": "agent-skill-loading@1",
            "match_on": "capability_description",
            "agent_action": (
                "reuse_matching_runtime_skill_else_load_after_trigger_"
                "and_approval"
            ),
        },
        "review_policy": {
            "policy_ref": "risk-tiered-review@1",
            "L1": "deterministic_only",
            "L2": "conditional_one",
            "L3": "one_specialist",
            "L4": "two_plus_third_on_conflict",
            "grill": "change_diff_only",
        },
    }
    if schema_version >= 2:
        context["report_requirements"] = report_requirements
        context["next_actions"] = next_actions
        context["entry_requirements"] = entry_requirements
        compact_frame = compact_entry_resolution_frame(
            entry_resolution_frame
        )
        if compact_frame is not None:
            context["entry_resolution"] = compact_frame
        context["node_report_requirement_refs"] = [
            *node.get("entry_report_refs", []),
            *node.get("node_report_refs", []),
        ]
        context["report_requirements"] = compact_report_requirements(
            context["report_requirements"]
        )
        context["next_actions"] = compact_next_actions(
            context["next_actions"]
        )
    packet_budget = graph_packet_budget(graph)
    if packet_budget.get("budget_scope") == "runtime_profile":
        context["budget_profile_ref"] = packet_budget["profile_ref"]
        context["budget_profile_hash"] = packet_budget["profile_hash"]
    ceiling_bytes = int(packet_budget["ceiling_bytes"])
    serialized_bytes = with_context_bytes(context)
    if serialized_bytes > min(ceiling_bytes, COMPACT_CONTEXT_TARGET_BYTES):
        context = _compact_context_for_budget(context)
        context = fit_compacted_context(
            context,
            target_bytes=min(ceiling_bytes, COMPACT_CONTEXT_TARGET_BYTES),
        )
        serialized_bytes = with_context_bytes(context)
    if serialized_bytes > ceiling_bytes:
        raise ValueError(
            "bounded context exceeds "
            f"{ceiling_bytes} bytes: {serialized_bytes}; "
            "request the detail packet before continuing"
        )
    return context, available_edges, ceiling_bytes


def build_graph_branch_context(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> dict[str, Any]:
    """Return current state without edge-selection instructions."""
    context, _, _ = _build_local_state(
        instance_id=instance_id,
        branch_id=branch_id,
        owner=owner,
    )
    return context
