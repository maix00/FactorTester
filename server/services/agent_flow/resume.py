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
from server.services.research_graph.branch.context import (
    build_graph_branch_context,
)


_ROLES = {"planning", "research", "server_maintenance"}


def build_agent_resume_packet(
    *,
    owner: str,
    agent_id: str,
    role: str,
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
    return packet


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
    source = build_graph_branch_context(
        instance_id=instance_id,
        branch_id=branch_id,
        owner=owner,
    )
    graph_ref = str(source.get("graph") or "")
    branch = dict(source.get("branch") or {})
    node = dict(source.get("node") or {})
    return {
        "graph": graph_ref,
        "branch": branch,
        "node": node,
        "current_node": str(node.get("node_id") or ""),
        "next_action": "download_graph_and_evaluate_locally",
        "graph_fetch": {
            "command": (
                "factortester research graphs fetch "
                f"{graph_ref.split('@v', 1)[0] if '@v' in graph_ref else graph_ref}"
            ),
            "transport": "7998_control_then_7997_data",
            "server_decides_next": False,
        },
        "local_cli": {
            "command": "factortester research graphs next-local",
            "requires": ["graph_file", "current_node"],
        },
        "running_backend_jobs_action": "continue",
    }


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
