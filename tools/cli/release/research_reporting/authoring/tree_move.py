"""Copy-on-write reparenting for a stable report component."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_navigation import contains_node, node_path, rewrite
from .tree_schema import identifier


def move_component(
    paths: dict[str, Path], head: dict[str, Any], root: dict[str, Any],
    component_id: str, parent_id: str, after_component_id: Any,
    pending_locators: list[tuple[str, str]], displaced: set[str],
    created: set[str],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    identifier(component_id, "component_id")
    identifier(parent_id, "parent_id")
    after = _after_id(after_component_id)
    nodes, edges = node_path(paths, root, component_id, head["generation"])
    if component_id == "root" or not edges:
        raise ValueError("root report component cannot be moved")
    if component_id == parent_id or contains_node(paths, nodes[-1], parent_id):
        raise ValueError("report move would create a hierarchy cycle")
    old_parent = nodes[-2]["node_id"]
    child_ref = edges[-1][0]["children"][edges[-1][1]]
    detached, changed_a, replaced_a = rewrite(
        paths, root, old_parent, head["generation"],
        lambda value: _remove_child(value, component_id), created=created,
    )
    moved, changed_b, replaced_b = rewrite(
        paths, detached, parent_id, head["generation"],
        lambda value: _insert_child(value, child_ref, after), created=created,
    )
    displaced.update(replaced_a)
    displaced.update(replaced_b)
    pending_locators.append((component_id, parent_id))
    changed = list(dict.fromkeys([*changed_a, *changed_b, component_id]))
    return head, moved, changed


def _after_id(value: Any) -> str | None:
    if value is None:
        return None
    return identifier(value, "after_component_id")


def _remove_child(
    parent: dict[str, Any], component_id: str,
) -> dict[str, Any]:
    matches = [
        index for index, child in enumerate(parent["children"])
        if child["node_id"] == component_id
    ]
    if len(matches) != 1:
        raise ValueError("report parent must contain the moved component once")
    parent["children"].pop(matches[0])
    return parent


def _insert_child(
    parent: dict[str, Any], child: dict[str, str], after: str | None,
) -> dict[str, Any]:
    if any(item["node_id"] == child["node_id"] for item in parent["children"]):
        raise ValueError("report parent contains duplicate child")
    if after is None:
        index = 0
    else:
        matches = [
            index for index, item in enumerate(parent["children"])
            if item["node_id"] == after
        ]
        if len(matches) != 1:
            raise ValueError("after_component_id must be a child of new parent")
        index = matches[0] + 1
    parent["children"].insert(index, child)
    return parent
