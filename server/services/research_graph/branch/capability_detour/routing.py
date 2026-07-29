"""Deterministic transition projection for one capability detour."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .state import (
    DETOUR_NODES, RESUME_EDGE_PREFIX, make_state, normalize_state,
)


def project_transition(
    state: dict[str, Any] | None,
    *,
    edge_id: str,
    source_node: str,
    target_node: str,
    trace_id: str,
) -> dict[str, Any]:
    current = normalize_state(state)
    if edge_id.startswith(RESUME_EDGE_PREFIX):
        if current is None:
            raise ValueError("capability detour has no interrupted node")
        if (
            source_node != "capability_resolution"
            or target_node != current["resume_node"]
        ):
            raise ValueError(
                "capability recovery must return to the original interrupted node"
            )
        return {"state": None, "delta": _delta("resumed", current, trace_id)}
    if current is not None:
        if source_node in DETOUR_NODES and target_node not in DETOUR_NODES:
            raise ValueError(
                "capability recovery requires the explicit original-node edge"
            )
        return {
            "state": current,
            "delta": _delta("retained", current, trace_id),
        }
    if target_node in DETOUR_NODES and source_node not in DETOUR_NODES:
        opened = make_state(source_node, trace_id)
        return {
            "state": opened,
            "delta": _delta("opened", opened, trace_id),
        }
    return {"state": None, "delta": None}


def _delta(
    status: str,
    state: dict[str, Any],
    trace_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": status,
        "episode_id": str(state["episode_id"]),
        "resume_node": str(state["resume_node"]),
        "origin_trace_id": str(state["origin_trace_id"]),
        "latest_trace_id": trace_id,
        "report_container": deepcopy(state["report_container"]),
    }
