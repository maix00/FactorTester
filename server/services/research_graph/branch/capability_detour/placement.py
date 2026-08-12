"""Available-edge and report-placement projection for capability detours."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .state import DETOUR_NODES, RESUME_EDGE_PREFIX, normalize_state


def contract_enabled(edges: list[dict[str, Any]]) -> bool:
    return any(
        str(edge.get("edge_id") or "").startswith(RESUME_EDGE_PREFIX)
        for edge in edges
    )


def requires_state(node_id: str) -> bool:
    """Only detour nodes can carry an active recovery state."""
    return node_id in DETOUR_NODES


def guard_facts(state: dict[str, Any] | None) -> dict[str, Any]:
    current = normalize_state(state)
    return {
        "capability_detour_resume_node": (
            str(current["resume_node"]) if current else ""
        ),
    }


def report_container(
    *,
    node_id: str,
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    current = normalize_state(state)
    if current is not None:
        return deepcopy(current["report_container"])
    if node_id in DETOUR_NODES:
        return {
            "kind": "special",
            "anchor_node": "",
            "episode_ref": "",
            "resume_node_required": True,
        }
    return {"kind": "chapter", "anchor_node": node_id}


def filter_available_edges(
    edges: list[dict[str, Any]],
    *,
    current_node: str,
    state: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    current = normalize_state(state)
    enabled = contract_enabled(edges)
    result = []
    for edge in edges:
        edge_id = str(edge.get("edge_id") or "")
        source = str(edge.get("from_node") or "")
        target = str(edge.get("to_node") or "")
        if source not in {current_node, "*"}:
            continue
        if not enabled:
            result.append(edge)
        elif edge_id.startswith(RESUME_EDGE_PREFIX):
            if current is not None and target == current["resume_node"]:
                result.append(edge)
        elif not (
            current is not None
            and current_node in DETOUR_NODES
            and target not in DETOUR_NODES
        ):
            result.append(edge)
    return result
