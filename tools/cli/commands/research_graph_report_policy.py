"""Declarative server-owned report-container policy for Graph nodes."""

from __future__ import annotations

from typing import Any

from tools.cli.core.context import client_from_config


def fetch_graph_node_packet(scope: Any) -> dict[str, Any]:
    instance_id, branch_id = graph_identity(scope)
    client = client_from_config()
    return client.get_research_graph_node_info(instance_id, branch_id)


def graph_identity(scope: Any) -> tuple[str, str]:
    parts = str(scope.branch_ref).split(":")
    if (
        len(parts) != 3
        or parts[0] != "graph-branch"
        or not parts[1]
        or parts[2] != scope.branch_id
    ):
        raise ValueError("report is not bound to a valid Graph branch")
    return parts[1], parts[2]


def report_container(packet: dict[str, Any]) -> dict[str, Any]:
    detour = packet.get("capability_detour")
    detour = detour if isinstance(detour, dict) else None
    raw = packet.get("report_container")
    if not isinstance(raw, dict) and detour is not None:
        raw = detour.get("report_container")
    if not isinstance(raw, dict):
        raise ValueError("Graph node has no declarative report_container")
    kind = str(raw.get("kind") or "")
    anchor = str(raw.get("anchor_node") or "")
    current_node = str(
        packet.get("current_node")
        or (packet.get("node") or {}).get("node_id")
        or ""
    )
    if kind == "chapter":
        if not anchor or anchor != current_node:
            raise ValueError("substantive report_container anchor is invalid")
        return {
            "kind": kind,
            "anchor_node": anchor,
            "current_node": current_node,
            "latest_trace_id": str(packet.get("latest_trace_id") or ""),
            "graph_ref": str(packet.get("graph") or ""),
            "entry_requirements": _entry_requirements(packet),
        }
    if kind != "special" or detour is None:
        raise ValueError("Graph report_container kind is unsupported")
    status = str(detour.get("status") or "")
    episode = str(detour.get("episode_id") or "")
    resume = str(detour.get("resume_node") or "")
    origin = str(detour.get("origin_trace_id") or "")
    latest_trace_id = str(
        detour.get("latest_trace_id")
        or packet.get("latest_trace_id")
        or ""
    )
    if (
        detour.get("schema_version") != 1
        or status not in {"pending", "opened", "retained", "resumed"}
        or not all((anchor, episode, resume, origin, current_node))
        or anchor != resume
        or raw.get("episode_ref") != episode
        or raw != detour.get("report_container")
        or raw.get("parent_episode_ref")
    ):
        raise ValueError("capability detour report_container is invalid")
    top = {
        "schema_version": 1,
        "episode_id": episode,
        "status": status,
        "resume_node": resume,
        "origin_trace_id": origin,
        "latest_trace_id": latest_trace_id,
        "report_container": dict(raw),
    }
    return {
        "kind": kind,
        "anchor_node": anchor,
        "current_node": current_node,
        "latest_trace_id": latest_trace_id,
        "graph_ref": str(packet.get("graph") or ""),
        "entry_requirements": _entry_requirements(packet),
        "detour": top,
    }


def _entry_requirements(packet: dict[str, Any]) -> list[dict[str, Any]]:
    value = packet.get("entry_requirements")
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
