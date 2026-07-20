"""Provider-neutral role-specific Agent startup and resume packets."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson

import settings as Settings
from server.services.maintenance_cases.queue import load_agent_case_queue
from server.services.research_configuration_summary import (
    load_workspace_factor_summary,
)
from server.services.research_graph.branch.next_packet import (
    build_graph_branch_next,
)
from server.services.research_graph.protocol import MAX_AGENT_PACKET_BYTES


_ROLES = {"planning", "research", "server_maintenance"}


def build_agent_resume_packet(
    *,
    owner: str,
    agent_id: str,
    role: str,
    budget_period: dict[str, Any] | None,
    instance_id: str = "",
    branch_id: str = "",
    workspace_id: str = "",
) -> dict[str, Any]:
    if role not in _ROLES:
        raise ValueError("unsupported Agent resume role")
    if not agent_id:
        raise ValueError("agent_id is required")
    packet = {
        "schema_version": 1,
        "agent": {
            "agent_id": agent_id,
            "role": role,
            "budget": _budget_summary(budget_period),
        },
    }
    if role == "research":
        packet["research"] = _research_packet(
            owner=owner,
            instance_id=instance_id,
            branch_id=branch_id,
        )
    elif role == "planning":
        packet["planning"] = _planning_packet(
            owner=owner,
            workspace_id=workspace_id,
        )
    else:
        packet["maintenance"] = _maintenance_packet(
            owner=owner,
            agent_id=agent_id,
        )
    packet["resume_ref"] = "sha256:" + hashlib.sha256(
        orjson.dumps(packet, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    packet["packet_bytes"] = 0
    for _ in range(3):
        packet["packet_bytes"] = len(orjson.dumps(packet))
    if len(orjson.dumps(packet)) > MAX_AGENT_PACKET_BYTES:
        raise ValueError(
            "Agent resume packet exceeds "
            f"{MAX_AGENT_PACKET_BYTES} bytes"
        )
    return packet


def _budget_summary(period: dict[str, Any] | None) -> dict[str, Any]:
    if period is None:
        return {
            "configured": False,
            "token_limit": None,
            "used_tokens": 0,
            "reserved_tokens": 0,
            "available_tokens": None,
            "exhausted": False,
        }
    limit = period.get("token_limit")
    available = period.get("available_tokens")
    return {
        "configured": limit is not None,
        "token_limit": limit,
        "used_tokens": int(period.get("used_tokens") or 0),
        "reserved_tokens": int(period.get("reserved_tokens") or 0),
        "available_tokens": available,
        "exhausted": limit is not None and int(available or 0) <= 0,
    }


def _research_packet(
    *,
    owner: str,
    instance_id: str,
    branch_id: str,
) -> dict[str, Any]:
    if not instance_id or not branch_id:
        raise ValueError(
            "research resume requires instance_id and branch_id"
        )
    value = build_graph_branch_next(
        instance_id=instance_id,
        branch_id=branch_id,
        owner=owner,
    )
    value.pop("next_bytes", None)
    obligations = value.get("current_obligations") or []
    recommended = value.get("recommended_edge_ids") or []
    value["next_action"] = (
        "address_current_obligations_and_candidate_edges"
        if obligations
        else f"advance:{recommended[0]}"
        if len(recommended) == 1
        else "review_candidate_edges"
    )
    return value


def _planning_packet(*, owner: str, workspace_id: str) -> dict[str, Any]:
    if not workspace_id:
        raise ValueError("planning resume requires workspace_id")
    summary = load_workspace_factor_summary(
        workspace_id=workspace_id,
        owner=owner,
    )
    return {
        "workspace_id": workspace_id,
        "factor_summary": summary,
        "pending_scope_decisions": [
            "product_scope",
            "initial_factor_focus",
        ],
        "next_action": (
            "confirm_product_scope_and_initial_factor_focus_with_user"
        ),
    }


def _maintenance_packet(*, owner: str, agent_id: str) -> dict[str, Any]:
    queue = load_agent_case_queue(
        db_path=Settings.CACHE_DB_PATH,
        owner_user_id=owner,
        agent_id=agent_id,
    )
    return {
        **queue,
        "next_action": (
            "claim_or_continue_first_case"
            if queue["cases"] else "wait_for_changed_case_ref"
        ),
    }
