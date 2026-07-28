"""Persistent-tree path resolution and copy-on-write ancestor replacement."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .tree_locators import load_locator
from .tree_schema import validate_node
from .tree_store import load_node, store_node


def rewrite(
    paths: dict[str, Path], root: dict[str, Any], target: str,
    visible_revision: int, transform: Callable[[dict[str, Any]], dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    nodes, edges = node_path(paths, root, target, visible_revision)
    value = validate_node(transform(deepcopy(nodes[-1])))
    changed = [target]
    for parent, child_index in reversed(edges):
        child_ref, _ = store_node(paths, value)
        updated = deepcopy(parent)
        updated["children"][child_index] = {
            "node_id": value["node_id"], "ref": child_ref,
        }
        value = validate_node(updated)
        changed.insert(0, value["node_id"])
    return value, changed


def contains_node(
    paths: dict[str, Path], node: dict[str, Any], node_id: str,
) -> bool:
    if node["node_id"] == node_id:
        return True
    return any(
        contains_node(paths, load_node(paths, child["ref"]), node_id)
        for child in node["children"]
    )


def node_path(
    paths: dict[str, Path], root: dict[str, Any], target: str,
    visible_revision: int,
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], int]]]:
    indexed = indexed_path(paths, root, target, visible_revision)
    if indexed is not None:
        return indexed
    scanned = scan_path(paths, root, target)
    if scanned is None:
        raise ValueError("report component does not exist")
    return scanned


def indexed_path(
    paths: dict[str, Path], root: dict[str, Any], target: str,
    visible_revision: int,
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], int]]] | None:
    if target == "root":
        return [root], []
    ids = [target]
    while ids[-1] != "root":
        locator = load_locator(paths, ids[-1])
        if locator is None or locator["revision"] > visible_revision:
            return None
        parent_id = locator["parent_id"]
        if parent_id in ids or len(ids) > 256:
            return None
        ids.append(parent_id)
    ids.reverse()
    nodes = [root]
    edges: list[tuple[dict[str, Any], int]] = []
    current = root
    for node_id in ids[1:]:
        index = next(
            (
                index for index, child in enumerate(current["children"])
                if child["node_id"] == node_id
            ),
            None,
        )
        if index is None:
            return None
        edges.append((current, index))
        current = load_node(paths, current["children"][index]["ref"])
        nodes.append(current)
    return nodes, edges


def scan_path(
    paths: dict[str, Path], node: dict[str, Any], target: str,
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], int]]] | None:
    if node["node_id"] == target:
        return [node], []
    for index, child in enumerate(node["children"]):
        found = scan_path(paths, load_node(paths, child["ref"]), target)
        if found is not None:
            nodes, edges = found
            return [node, *nodes], [(node, index), *edges]
    return None
