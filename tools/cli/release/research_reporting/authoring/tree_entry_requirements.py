"""System-owned obligation-requirements overview for one Graph node."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .inline_links import typed_link_list
from .special_section_operation import add_special_section_operation
from .tree_model import apply_batch
from .tree_projection import load_snapshot


def ensure_entry_requirements_summary(
    *,
    package_root: Path,
    branch_id: str,
    parent_id: str,
    graph_ref: str,
    node_id: str,
    requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create one immutable overview only when node checks are present."""
    rows = _rows(requirements)
    if not rows:
        return {"changed": False, "component_id": ""}
    component_id = _component_id(graph_ref, node_id)
    snapshot = load_snapshot(
        package_root=package_root, branch_id=branch_id,
    )
    existing = next((
        item for item in snapshot["components"]
        if item["component_id"] == component_id
    ), None)
    if existing is not None:
        if (
            existing["kind"] != "special"
            or existing["display_kind"] != "entry_requirements"
            or existing["parent_id"] != parent_id
        ):
            raise ValueError("node-check overview identity is already occupied")
        return {"changed": False, "component_id": component_id}
    operation, _ = entry_requirements_summary_operation(
        parent_id=parent_id,
        graph_ref=graph_ref,
        node_id=node_id,
        requirements=rows,
    )
    apply_batch(
        package_root=package_root,
        branch_id=branch_id,
        operations=[operation],
        include_snapshot=False,
    )
    return {"changed": True, "component_id": component_id}


def entry_requirements_summary_operation(
    *,
    parent_id: str,
    graph_ref: str,
    node_id: str,
    requirements: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    """Build the same overview as one report batch operation."""
    rows = _rows(requirements)
    if not rows:
        raise ValueError("node obligation requirements are empty")
    component_id = _component_id(graph_ref, node_id)
    links = [{
        "kind": "entry_requirement",
        "target_ref": f"requirement:{item['requirement_id']}",
        "label": item["title_zh"] or item["requirement_id"],
    } for item in rows]
    bindings = [{
        "binding_id": f"entry-requirements-node-{_digest(graph_ref, node_id)}",
        "kind": "graph_reference",
        "target_ref": f"node:{node_id}",
        "label": "节点义务要求",
        "data": {
            "role": "obligation_requirements_summary",
            "graph_ref": graph_ref,
        },
    }] + [{
        "binding_id": (
            "reference-entry-requirement-" + _digest(
                graph_ref, node_id, item["requirement_id"],
            )
        ),
        "kind": "entry_requirement",
        "target_ref": f"requirement:{item['requirement_id']}",
        "label": item["title_zh"] or item["requirement_id"],
        "data": {
            "graph_ref": graph_ref,
            "node_id": node_id,
            **item,
        },
    } for item in rows]
    return add_special_section_operation(
        component_id=component_id,
        title="节点义务要求",
        parent_id=parent_id,
        body=typed_link_list(links),
        content={"schema_version": 1, "requirements": rows},
        display_kind="entry_requirements",
        bindings=bindings,
    ), component_id


def _rows(value: list[dict[str, Any]]) -> list[dict[str, str]]:
    result = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        requirement_id = str(item.get("requirement_id") or "").strip()
        if not requirement_id or requirement_id in seen:
            continue
        seen.add(requirement_id)
        result.append({
            "requirement_id": requirement_id,
            "title_zh": str(item.get("title_zh") or ""),
            "gate_policy": str(item.get("gate_policy") or ""),
            "detail_ref": str(
                item.get("detail_ref")
                or f"graph-requirement:{requirement_id}"
            ),
        })
    return result


def _component_id(graph_ref: str, node_id: str) -> str:
    return "entry-requirements-" + _digest(graph_ref, node_id)


def _digest(*values: str) -> str:
    return hashlib.sha256("\x1f".join(values).encode()).hexdigest()[:40]
