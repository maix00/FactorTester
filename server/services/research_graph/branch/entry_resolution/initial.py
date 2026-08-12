"""Graph-continuation bootstrap for canonical entry-resolution state."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .projection import project_entry_attempt
from .stack_routing import project_target_frame
from .stack_state import canonical_entry_resolution_state, text_ids


def initial_entry_resolution_frame(
    descriptor: dict[str, Any],
    *,
    inherited_frame: dict[str, Any] | None = None,
    checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = canonical_entry_resolution_state(inherited_frame)
    if descriptor.get("continuation_mode") != "same_node_reentry":
        return state
    preflight = descriptor.get("requirement_preflight")
    if not isinstance(preflight, dict):
        return state
    unresolved = text_ids(preflight.get("assessment_required_ids"))
    if not unresolved:
        return state
    graph = {
        "graph_id": str(descriptor.get("graph_id") or ""),
        "version": int(descriptor.get("target_graph_version") or 0),
        "content_hash": str(descriptor.get("target_graph_hash") or ""),
        "nodes": [{
            "node_id": str(descriptor.get("target_node") or ""),
            "entry_requirement_refs": unresolved,
        }],
    }
    frame = project_entry_attempt(
        graph=graph,
        target_node=str(descriptor.get("target_node") or ""),
        checkpoint=checkpoint,
        origin_ref=_continuation_origin(descriptor),
        unresolved_requirement_refs=unresolved,
        resolved_requirement_refs=[],
    )
    frame["continuation_preflight"] = {
        "reason": "graph_continuation",
        "source_graph_version": int(
            descriptor.get("source_graph_version") or 0
        ),
        "target_graph_version": int(
            descriptor.get("target_graph_version") or 0
        ),
        "requirement_delta_hash": str(preflight.get("delta_hash") or ""),
        "added_requirement_ids": text_ids(preflight.get("entry_added_ids")),
        "revised_requirement_ids": text_ids(
            preflight.get("entry_revised_ids")
        ),
        "removed_requirement_ids": text_ids(
            preflight.get("entry_removed_ids")
        ),
        "metadata_changed_requirement_ids": text_ids(
            preflight.get("entry_metadata_changed_ids")
        ),
    }
    target = frame["target_node"]
    return project_target_frame(
        state=state,
        target_frame=frame,
        current_node=target,
        target_node=target,
    )


def _continuation_origin(descriptor: dict[str, Any]) -> str:
    fields = (
        descriptor.get("source_instance_id"),
        descriptor.get("source_branch_id"),
        descriptor.get("source_trace_id"),
        descriptor.get("target_graph_version"),
    )
    if not all(str(item or "") for item in fields):
        raise ValueError("entry continuation origin is incomplete")
    return "graph-continuation:" + ":".join(str(item) for item in fields)
