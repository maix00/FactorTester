"""One semantic operation planner for a capability-detour report special."""

from __future__ import annotations

import hashlib
from typing import Any

from .special_section_operation import add_special_section_operation


def capability_detour_operations(
    *,
    snapshot: dict[str, Any],
    parent_id: str,
    detour: dict[str, Any],
    current_node: str,
    latest_trace_id: str = "",
    component_id_hint: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """Plan one idempotent detour update without changing report placement."""
    episode = str(detour.get("episode_id") or "")
    origin = str(detour.get("origin_trace_id") or "")
    resume = str(detour.get("resume_node") or "")
    status = str(detour.get("status") or "")
    if not all((episode, origin, resume, status)):
        raise ValueError("capability detour report metadata is incomplete")

    components = {
        str(item["component_id"]): item
        for item in snapshot["components"]
    }
    bindings = _bindings_by_component(snapshot["bindings"])
    bound = {
        str(item["component_id"])
        for item in snapshot["bindings"]
        if _is_detour_binding(item, episode)
    }
    if len(bound) > 1:
        raise ValueError("capability detour episode has multiple report specials")
    if bound and component_id_hint and component_id_hint not in bound:
        raise ValueError("capability detour component hint conflicts with binding")
    component_id = (
        next(iter(bound), "")
        or component_id_hint
        or "special-capability-" + _short(episode)
    )
    existing = components.get(component_id)
    if existing is not None and existing["kind"] != "special":
        raise ValueError("capability detour report container must be special")

    binding = _detour_binding(
        episode=episode,
        origin=origin,
        resume=resume,
    )
    content = _detour_content(
        previous=(existing or {}).get("content"),
        episode=episode,
        origin=origin,
        resume=resume,
        status=status,
        current_node=current_node,
        latest_trace_id=(latest_trace_id or str(
            detour.get("latest_trace_id") or ""
        )),
    )
    if existing is None:
        return [add_special_section_operation(
            component_id=component_id,
            title="能力修复过程",
            parent_id=parent_id,
            content=content,
            display_kind="capability_detour",
            bindings=[binding],
        )], component_id

    operations: list[dict[str, Any]] = []
    if (
        existing["parent_id"] != parent_id
        and not _nested_in_semantic_special(
            component=existing,
            expected_parent_id=parent_id,
            components=components,
        )
    ):
        operations.append({
            "op": "move",
            "component_id": component_id,
            "parent_id": parent_id,
        })
    current_bindings = bindings.get(component_id, [])
    if not any(_is_detour_binding(item, episode) for item in current_bindings):
        current_bindings = [*current_bindings, binding]
    if any((
        existing.get("content") != content,
        existing.get("display_kind") != "capability_detour",
        current_bindings != bindings.get(component_id, []),
    )):
        operations.append({
            "op": "replace",
            "component_id": component_id,
            "kind": "special",
            "title": str(existing.get("title") or "能力修复过程"),
            "body": str(existing.get("body") or ""),
            "content": content,
            "display_kind": "capability_detour",
            "bindings": current_bindings,
        })
    return operations, component_id


def _detour_content(
    *, previous: Any, episode: str, origin: str, resume: str, status: str,
    current_node: str, latest_trace_id: str,
) -> dict[str, Any]:
    prior = previous if isinstance(previous, dict) else {}
    transitions = list(prior.get("transitions") or [])
    trace_ref = f"trace:{latest_trace_id}" if latest_trace_id else ""
    matches = [
        item for item in transitions
        if isinstance(item, dict) and item.get("trace_ref") == trace_ref
    ]
    if len(matches) > 1 or any(
        str(item.get("node_id") or "") != current_node for item in matches
    ):
        raise ValueError("capability detour trace projection conflicts")
    if trace_ref and not matches:
        transitions.append({
            "trace_ref": trace_ref,
            "status": status,
            "node_id": current_node,
        })
    return {
        **prior,
        "schema_version": 1,
        "episode_ref": episode,
        "status": status,
        "resume_node": resume,
        "origin_trace_ref": f"trace:{origin}",
        "transitions": transitions,
    }


def _nested_in_semantic_special(
    *, component: dict[str, Any], expected_parent_id: str,
    components: dict[str, dict[str, Any]],
) -> bool:
    parent_id = str(component.get("parent_id") or "")
    parent = components.get(parent_id)
    if parent is None or parent.get("kind") != "special":
        return False
    seen = {str(component.get("component_id") or "")}
    while parent_id:
        if parent_id in seen:
            raise ValueError("report hierarchy contains a parent cycle")
        if parent_id == expected_parent_id:
            return True
        seen.add(parent_id)
        parent_id = str((components.get(parent_id) or {}).get("parent_id") or "")
    return False


def _detour_binding(*, episode: str, origin: str, resume: str) -> dict[str, Any]:
    return {
        "binding_id": "special-capability-" + _short(episode),
        "kind": "graph_reference",
        "target_ref": episode,
        "label": "能力修复过程",
        "data": {
            "role": "capability_detour",
            "resume_node": resume,
            "origin_trace_ref": f"trace:{origin}",
        },
    }


def _is_detour_binding(item: dict[str, Any], episode: str) -> bool:
    return (
        item.get("kind") == "graph_reference"
        and item.get("target_ref") == episode
        and (item.get("data") or {}).get("role") == "capability_detour"
    )


def _bindings_by_component(
    values: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for item in values:
        result.setdefault(str(item["component_id"]), []).append({
            key: value for key, value in item.items()
            if key != "component_id"
        })
    return result


def _short(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]
