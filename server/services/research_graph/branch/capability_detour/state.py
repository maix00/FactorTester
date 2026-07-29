"""Canonical state for one active capability-detour episode."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..continuation_frame import normalized_continuation_identity


DETOUR_NODES = frozenset({
    "capability_gap",
    "capability_resolution",
    "skill_candidate_review",
    "code_improvement_required",
})
RESUME_EDGE_PREFIX = "capability_resolution__resume_"


def make_state(resume_node: Any, origin_trace_id: Any) -> dict[str, Any]:
    resume = str(resume_node or "")
    origin = str(origin_trace_id or "")
    episode_id = f"capability-detour:{origin}"
    identity = normalized_continuation_identity(
        resume_node=resume,
        origin_ref=origin,
    )
    return {
        "schema_version": 1,
        "status": "pending",
        "episode_id": episode_id,
        "resume_node": identity["resume_node"],
        "origin_trace_id": identity["origin_ref"],
        "report_container": {
            "kind": "special",
            "anchor_node": resume,
            "episode_ref": episode_id,
        },
    }


def normalize_state(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("status") != "pending":
        return None
    if value.get("resume_node") and value.get("origin_trace_id"):
        state = make_state(value["resume_node"], value["origin_trace_id"])
        container = value.get("report_container")
        if isinstance(container, dict):
            state["report_container"] = deepcopy(container)
        return state
    frames = value.get("frames")
    if isinstance(frames, list) and len(frames) == 1:
        return normalize_state({**frames[0], "status": "pending"})
    return None
