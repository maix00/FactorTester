"""Compatibility projection for traces written before detour deltas."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .placement import report_container
from .state import DETOUR_NODES, RESUME_EDGE_PREFIX, normalize_state


def legacy_exit(
    state: Any,
    edge_id: str,
    source: str,
    target: str,
) -> bool:
    current = normalize_state(state)
    if current is None or edge_id.startswith(RESUME_EDGE_PREFIX):
        return False
    return source in DETOUR_NODES and target not in DETOUR_NODES


def historical_container(
    *,
    node_id: str,
    state: Any,
    legacy_untracked: bool,
) -> dict[str, Any]:
    if (
        legacy_untracked
        and normalize_state(state) is None
        and node_id in DETOUR_NODES
        and node_id != "capability_gap"
    ):
        return {"kind": "chapter", "anchor_node": node_id}
    return report_container(node_id=node_id, state=state)


def legacy_delta(
    state: Any,
    trace_id: str,
    *,
    exit_node: str,
) -> dict[str, Any]:
    status = (
        "resumed"
        if exit_node == str(state["resume_node"])
        else "legacy_exited"
    )
    return {
        "schema_version": 1,
        "status": status,
        **{
            key: str(state[key])
            for key in ("episode_id", "resume_node", "origin_trace_id")
        },
        "latest_trace_id": trace_id,
        "exit_node": exit_node,
        "report_container": deepcopy(state["report_container"]),
        "legacy_edge": True,
    }
