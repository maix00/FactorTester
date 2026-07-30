"""Trusted removal of one report subtree after migration validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_navigation import node_path, rewrite
from .tree_schema import identifier
from .tree_store import load_node


def remove_component(
    paths: dict[str, Path],
    head: dict[str, Any],
    root: dict[str, Any],
    component_id: str,
    *,
    allow_subtree: bool,
    displaced: set[str],
    created: set[str],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Detach a migration-validated component from the authoritative tree."""
    identifier(component_id, "component_id")
    nodes, edges = node_path(
        paths, root, component_id, head["generation"],
    )
    if component_id == "root" or not edges:
        raise ValueError("root report component cannot be removed")
    target = nodes[-1]
    if target["children"] and not allow_subtree:
        raise ValueError("non-empty report component cannot be removed")
    parent_id = nodes[-2]["node_id"]
    child_ref = edges[-1][0]["children"][edges[-1][1]]["ref"]
    displaced.update(_subtree_references(paths, child_ref))
    rewritten, changed, replaced = rewrite(
        paths,
        root,
        parent_id,
        head["generation"],
        lambda value: _without_child(value, component_id),
        created=created,
    )
    displaced.update(replaced)
    return head, rewritten, [*changed, component_id]


def _without_child(
    parent: dict[str, Any], component_id: str,
) -> dict[str, Any]:
    matches = [
        index for index, child in enumerate(parent["children"])
        if child["node_id"] == component_id
    ]
    if len(matches) != 1:
        raise ValueError("report parent must contain the component once")
    parent["children"].pop(matches[0])
    return parent


def _subtree_references(
    paths: dict[str, Path], reference: str,
) -> set[str]:
    result = {reference}
    node = load_node(paths, reference)
    for child in node["children"]:
        result.update(_subtree_references(paths, child["ref"]))
    return result
