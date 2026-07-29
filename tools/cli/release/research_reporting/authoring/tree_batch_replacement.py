"""Validation for one replacement in an atomic report batch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_navigation import node_path
from .tree_replacement import retained_attached_bindings
from .tree_schema import identifier, validate_binding, validate_node


def validate_replace(
    paths: dict[str, Path], head: dict[str, Any], root: dict[str, Any],
    operation: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    component_id = identifier(
        str(operation.get("component_id") or ""), "component_id",
    )
    if component_id == "root" or "parent_id" in operation:
        raise ValueError("replace cannot move a report component")
    required = {"title", "body", "content", "display_kind"}
    if not required.issubset(operation):
        raise ValueError("replace requires all authored component fields")
    current = node_path(
        paths, root, component_id, head["generation"],
    )[0][-1]
    kind = str(operation.get("kind") or current["kind"])
    if kind != current["kind"]:
        raise ValueError("replace cannot change report component kind")
    raw_bindings = operation.get("bindings")
    if not isinstance(raw_bindings, list):
        raise ValueError("replacement bindings must be an array")
    bindings = [validate_binding(item) for item in raw_bindings]
    validate_node({
        **current,
        "title": str(operation.get("title") or ""),
        "body": str(operation.get("body") or ""),
        "content": operation.get("content"),
        "display_kind": str(operation.get("display_kind") or ""),
        "bindings": [
            *retained_attached_bindings(current["bindings"]),
            *bindings,
        ],
    })
    return component_id, bindings
