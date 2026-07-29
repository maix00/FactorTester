"""Prewrite simulation of hierarchy changes in one report batch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_hierarchy import validate_parent_child, validate_root_child
from .tree_schema import NODE_KINDS, identifier
from .tree_store import load_node

_MOVE_FIELDS = {"op", "component_id", "parent_id", "after_component_id"}
_MOVE_REQUIRED = {"op", "component_id", "parent_id"}


def validate_hierarchy_plan(
    paths: dict[str, Path], root: dict[str, Any],
    operations: list[dict[str, Any]],
) -> None:
    kinds: dict[str, str] = {}
    parents: dict[str, str | None] = {}
    children: dict[str, list[str]] = {}
    _collect(paths, root, None, kinds, parents, children)
    added: set[str] = set()
    moved: set[str] = set()
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        if operation.get("op") == "add":
            _add(operation, kinds, parents, children, added)
        elif operation.get("op") == "move":
            component_id = _move(
                operation, kinds, parents, children,
            )
            if component_id in moved:
                raise ValueError("report batch moves component more than once")
            moved.add(component_id)


def _collect(
    paths: dict[str, Path], node: dict[str, Any], parent_id: str | None,
    kinds: dict[str, str], parents: dict[str, str | None],
    children: dict[str, list[str]],
) -> None:
    node_id = node["node_id"]
    if node_id in kinds:
        raise ValueError("report tree contains duplicate child")
    kinds[node_id] = node["kind"]
    parents[node_id] = parent_id
    ids = [str(child["node_id"]) for child in node["children"]]
    if len(ids) != len(set(ids)):
        raise ValueError("report parent contains duplicate child")
    children[node_id] = ids
    for child in node["children"]:
        _collect(
            paths, load_node(paths, child["ref"]), node_id,
            kinds, parents, children,
        )


def _add(
    operation: dict[str, Any], kinds: dict[str, str],
    parents: dict[str, str | None], children: dict[str, list[str]],
    added: set[str],
) -> None:
    component_id = identifier(
        str(operation.get("component_id") or ""), "component_id",
    )
    if component_id in kinds:
        if component_id in added:
            raise ValueError("report batch duplicates component_id")
        raise ValueError("component_id already exists")
    kind = str(operation.get("kind") or "")
    if kind not in NODE_KINDS:
        raise ValueError("unsupported report component kind")
    parent_id = str(operation.get("parent_id") or "root")
    identifier(parent_id, "parent_id")
    validate_root_child(kind=kind, parent_id=parent_id)
    if parent_id not in kinds:
        raise ValueError("report component does not exist")
    validate_parent_child(
        parent_kind=kinds[parent_id], child_kind=kind,
    )
    kinds[component_id] = kind
    parents[component_id] = parent_id
    children[component_id] = []
    children[parent_id].append(component_id)
    added.add(component_id)


def _move(
    operation: dict[str, Any], kinds: dict[str, str],
    parents: dict[str, str | None], children: dict[str, list[str]],
) -> str:
    if (
        not _MOVE_REQUIRED.issubset(operation)
        or not set(operation).issubset(_MOVE_FIELDS)
    ):
        raise ValueError("move operation fields are invalid")
    component_id = identifier(
        str(operation.get("component_id") or ""), "component_id",
    )
    parent_id = identifier(
        str(operation.get("parent_id") or ""), "parent_id",
    )
    if component_id == "root" or component_id not in kinds:
        raise ValueError("root or missing report component cannot be moved")
    if parent_id not in kinds:
        raise ValueError("report component does not exist")
    if _descends_from(parent_id, component_id, parents):
        raise ValueError("report move would create a hierarchy cycle")
    validate_parent_child(
        parent_kind=kinds[parent_id], child_kind=kinds[component_id],
    )
    old_parent = parents[component_id]
    if old_parent is None or children[old_parent].count(component_id) != 1:
        raise ValueError("report parent must contain moved component once")
    children[old_parent].remove(component_id)
    after = operation.get("after_component_id")
    if after is not None:
        after = identifier(after, "after_component_id")
    _insert(children[parent_id], component_id, after)
    parents[component_id] = parent_id
    return component_id


def _insert(values: list[str], component_id: str, after: str | None) -> None:
    if component_id in values:
        raise ValueError("report parent contains duplicate child")
    if after is None:
        values.insert(0, component_id)
        return
    if after not in values:
        raise ValueError("after_component_id must belong to same parent")
    values.insert(values.index(after) + 1, component_id)


def _descends_from(
    node_id: str, ancestor_id: str, parents: dict[str, str | None],
) -> bool:
    current: str | None = node_id
    while current is not None:
        if current == ancestor_id:
            return True
        current = parents[current]
    return False
