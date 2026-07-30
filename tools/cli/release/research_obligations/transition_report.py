"""Report operations that atomically finish one accepted Graph transition."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tools.cli.release.research_reporting.authoring.tree_entry_requirements import (
    entry_requirements_summary_operation,
)
from tools.cli.release.research_reporting.authoring.tree_projection import (
    load_snapshot,
)
from tools.cli.release.research_reporting.node_titles import node_title_zh


def target_container_operations(
    *,
    package_root: Path,
    branch_id: str,
    container: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Create/update the target report container in the receipt batch."""
    snapshot = load_snapshot(package_root=package_root, branch_id=branch_id)
    components = {
        str(item["component_id"]): item for item in snapshot["components"]
    }
    bindings = _bindings_by_component(snapshot["bindings"])
    operations: list[dict[str, Any]] = []
    anchor = str(container.get("anchor_node") or "")
    chapter_id = _bound_component(
        snapshot["bindings"],
        kind="graph_reference",
        target_ref=f"node:{anchor}",
        role="report_chapter",
    ) or f"chapter-{_short(anchor)}"
    chapter = components.get(chapter_id)
    title = node_title_zh(anchor)
    if chapter is None:
        operations.append(_chapter_add(chapter_id, anchor, title))
    else:
        if chapter["kind"] != "chapter":
            raise ValueError("target Graph chapter identity is occupied")
        if chapter["title"] != title:
            operations.append(_replace(
                chapter,
                title=title,
                bindings=bindings.get(chapter_id, []),
            ))
    parent_id = chapter_id
    target_id = chapter_id
    if container.get("kind") == "special":
        special_ops, target_id = _detour_operations(
            container=container,
            components=components,
            bindings=bindings,
            parent_id=chapter_id,
        )
        operations.extend(special_ops)
        parent_id = target_id
    elif container.get("kind") != "chapter":
        raise ValueError("target Graph report container is unsupported")
    requirements = container.get("entry_requirements")
    summary_id = ""
    if isinstance(requirements, list) and requirements:
        summary, summary_id = entry_requirements_summary_operation(
            parent_id=parent_id,
            graph_ref=str(container.get("graph_ref") or ""),
            node_id=str(container.get("current_node") or ""),
            requirements=requirements,
        )
        existing = components.get(summary_id)
        if existing is None:
            operations.append(summary)
        elif (
            existing["kind"] != "special"
            or existing["display_kind"] != "entry_requirements"
            or existing["parent_id"] != parent_id
        ):
            raise ValueError("target node obligation overview identity conflicts")
    return operations, {
        "chapter_id": chapter_id,
        "container_id": target_id,
        "requirements_summary_id": summary_id,
    }


def _detour_operations(
    *,
    container: dict[str, Any],
    components: dict[str, dict[str, Any]],
    bindings: dict[str, list[dict[str, Any]]],
    parent_id: str,
) -> tuple[list[dict[str, Any]], str]:
    detour = container.get("detour")
    if not isinstance(detour, dict):
        raise ValueError("target special container has no capability detour")
    episode = str(detour.get("episode_id") or "")
    if not episode:
        raise ValueError("target capability detour episode is absent")
    component_id = f"special-capability-{_short(episode)}"
    binding = _detour_binding(detour)
    existing = components.get(component_id)
    content = _detour_content(
        detour=detour,
        current_node=str(container.get("current_node") or ""),
        previous=(existing or {}).get("content"),
    )
    if existing is None:
        return [{
            "op": "add",
            "component_id": component_id,
            "kind": "special",
            "title": "能力修复过程",
            "parent_id": parent_id,
            "body": "",
            "content": content,
            "display_kind": "capability_detour",
            "bindings": [binding],
        }], component_id
    if existing["kind"] != "special":
        raise ValueError("target capability detour identity is occupied")
    operations = []
    if existing["parent_id"] != parent_id:
        operations.append({
            "op": "move",
            "component_id": component_id,
            "parent_id": parent_id,
        })
    current_bindings = bindings.get(component_id, [])
    if not any(
        item["kind"] == "graph_reference"
        and item["target_ref"] == episode
        and (item.get("data") or {}).get("role") == "capability_detour"
        for item in current_bindings
    ):
        current_bindings = [*current_bindings, binding]
    if (
        existing["content"] != content
        or existing["display_kind"] != "capability_detour"
        or current_bindings != bindings.get(component_id, [])
    ):
        operations.append(_replace(
            existing,
            title="能力修复过程",
            content=content,
            display_kind="capability_detour",
            bindings=current_bindings,
        ))
    return operations, component_id


def _chapter_add(component_id: str, node_id: str, title: str) -> dict[str, Any]:
    return {
        "op": "add",
        "component_id": component_id,
        "kind": "chapter",
        "title": title,
        "parent_id": None,
        "body": "",
        "content": None,
        "display_kind": "",
        "bindings": [{
            "binding_id": f"chapter-node-{_short(node_id)}",
            "kind": "graph_reference",
            "target_ref": f"node:{node_id}",
            "label": title,
            "data": {
                "role": "report_chapter",
                "chapter_ref": f"node:{node_id}",
            },
        }],
    }


def _detour_binding(detour: dict[str, Any]) -> dict[str, Any]:
    episode = str(detour["episode_id"])
    return {
        "binding_id": f"special-capability-{_short(episode)}",
        "kind": "graph_reference",
        "target_ref": episode,
        "label": "能力修复过程",
        "data": {
            "role": "capability_detour",
            "resume_node": str(detour.get("resume_node") or ""),
            "origin_trace_ref": (
                f"trace:{str(detour.get('origin_trace_id') or '')}"
            ),
        },
    }


def _detour_content(
    *,
    detour: dict[str, Any],
    current_node: str,
    previous: Any,
) -> dict[str, Any]:
    prior = previous if isinstance(previous, dict) else {}
    transitions = list(prior.get("transitions") or [])
    latest = str(detour.get("latest_trace_id") or "")
    trace_ref = f"trace:{latest}" if latest else ""
    matches = [
        item for item in transitions
        if isinstance(item, dict) and item.get("trace_ref") == trace_ref
    ]
    if len(matches) > 1 or any(
        str(item.get("node_id") or "") != current_node for item in matches
    ):
        raise ValueError("target capability detour trace conflicts")
    if trace_ref and not matches:
        transitions.append({
            "trace_ref": trace_ref,
            "status": str(detour.get("status") or ""),
            "node_id": current_node,
        })
    return {
        **prior,
        "schema_version": 1,
        "episode_ref": str(detour["episode_id"]),
        "status": str(detour.get("status") or ""),
        "resume_node": str(detour.get("resume_node") or ""),
        "origin_trace_ref": (
            f"trace:{str(detour.get('origin_trace_id') or '')}"
        ),
        "transitions": transitions,
    }


def _replace(
    component: dict[str, Any],
    *,
    title: str,
    bindings: list[dict[str, Any]],
    content: Any = None,
    display_kind: str | None = None,
) -> dict[str, Any]:
    return {
        "op": "replace",
        "component_id": str(component["component_id"]),
        "kind": str(component["kind"]),
        "title": title,
        "body": str(component.get("body") or ""),
        "content": (
            component.get("content") if content is None else content
        ),
        "display_kind": (
            str(component.get("display_kind") or "")
            if display_kind is None else display_kind
        ),
        "bindings": bindings,
    }


def _bindings_by_component(
    values: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for item in values:
        component_id = str(item["component_id"])
        result.setdefault(component_id, []).append({
            key: value for key, value in item.items()
            if key != "component_id"
        })
    return result


def _bound_component(
    values: list[dict[str, Any]],
    *,
    kind: str,
    target_ref: str,
    role: str,
) -> str:
    matches = {
        str(item["component_id"]) for item in values
        if item["kind"] == kind
        and item["target_ref"] == target_ref
        and (item.get("data") or {}).get("role") == role
    }
    if len(matches) > 1:
        raise ValueError("target report container has multiple bindings")
    return next(iter(matches), "")


def _short(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]
