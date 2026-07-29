"""System-owned report projection for one capability-detour episode."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .tree_model import add_component, load_snapshot
from .tree_system_mutations import move_system_component, replace_system_component


def ensure_capability_detour_special(
    *,
    package_root: Path,
    branch_id: str,
    parent_id: str,
    detour: dict[str, Any],
    current_node: str,
    latest_trace_id: str,
    component_id_hint: str = "",
) -> dict[str, Any]:
    episode = str(detour.get("episode_id") or "")
    origin = str(detour.get("origin_trace_id") or "")
    resume = str(detour.get("resume_node") or "")
    status = str(detour.get("status") or "")
    if not all((episode, origin, resume, status)):
        raise ValueError("capability detour report metadata is incomplete")
    suffix = hashlib.sha256(episode.encode()).hexdigest()[:16]
    deterministic_id = "special-capability-" + suffix
    binding = {
        "binding_id": "special-capability-" + suffix,
        "kind": "graph_reference",
        "target_ref": episode,
        "label": "能力修复过程",
        "data": {
            "role": "capability_detour",
            "resume_node": resume,
            "origin_trace_ref": f"trace:{origin}",
        },
    }
    snapshot = load_snapshot(package_root=package_root, branch_id=branch_id)
    bound = {
        item["component_id"] for item in snapshot["bindings"]
        if item["kind"] == "graph_reference"
        and item["target_ref"] == episode
        and (item.get("data") or {}).get("role") == "capability_detour"
    }
    if len(bound) > 1:
        raise ValueError("capability detour episode has multiple report specials")
    if bound and component_id_hint and component_id_hint not in bound:
        raise ValueError("capability detour component hint conflicts with binding")
    component_id = next(iter(bound), "") or component_id_hint or deterministic_id
    existing = next((
        item for item in snapshot["components"]
        if item["component_id"] == component_id
    ), None)
    if existing is not None and existing["kind"] != "special":
        raise ValueError("capability detour report container must be special")
    moved = existing is not None and existing["parent_id"] != parent_id
    if moved:
        move_system_component(
            package_root=package_root, branch_id=branch_id,
            component_id=component_id, parent_id=parent_id,
        )
        snapshot = load_snapshot(package_root=package_root, branch_id=branch_id)
        existing = next(
            item for item in snapshot["components"]
            if item["component_id"] == component_id
        )
    previous_content = (
        existing.get("content") if isinstance(existing, dict) else {}
    )
    transitions = list(
        (previous_content if isinstance(previous_content, dict) else {})
        .get("transitions") or []
    )
    trace_ref = f"trace:{latest_trace_id}" if latest_trace_id else ""
    matches = [
        item for item in transitions
        if isinstance(item, dict) and item.get("trace_ref") == trace_ref
    ]
    if matches and matches != [{
        "trace_ref": trace_ref, "status": status, "node_id": current_node,
    }]:
        raise ValueError("capability detour trace projection conflicts")
    if trace_ref and not matches:
        transitions.append({
            "trace_ref": trace_ref, "status": status, "node_id": current_node,
        })
    projected_status = str(
        (transitions[-1] if transitions else {}).get("status") or status
    )
    content = {
        **(previous_content if isinstance(previous_content, dict) else {}),
        "schema_version": 1,
        "episode_ref": episode,
        "status": projected_status,
        "resume_node": resume,
        "origin_trace_ref": f"trace:{origin}",
        "transitions": transitions,
    }
    if existing is None:
        saved = add_component(
            package_root=package_root, branch_id=branch_id,
            component_id=component_id, kind="special",
            title="能力修复过程", parent_id=parent_id, body="",
            content=content, display_kind="capability_detour",
            bindings=[binding], include_snapshot=False,
        )
        changed = True
    else:
        bindings = [
            item for item in snapshot["bindings"]
            if item["component_id"] == component_id
        ]
        original_binding_count = len(bindings)
        if not any(
            item["kind"] == "graph_reference"
            and item["target_ref"] == episode
            and (item.get("data") or {}).get("role") == "capability_detour"
            for item in bindings
        ):
            bindings.append(binding)
        replacement = {
            **existing,
            "content": content,
            "display_kind": "capability_detour",
        }
        changed = moved or any((
            existing.get("content") != content,
            existing.get("display_kind") != "capability_detour",
            len(bindings) != original_binding_count,
        ))
        saved = replace_system_component(
            package_root=package_root,
            branch_id=branch_id,
            component=replacement,
            bindings=bindings,
        ) if changed else snapshot
    return {
        "changed": changed,
        "component_id": component_id,
        "paths": saved["paths"],
        "head": saved["head"],
        "components": [],
        "bindings": [],
    }
