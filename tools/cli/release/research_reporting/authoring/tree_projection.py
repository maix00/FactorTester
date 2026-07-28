"""Read-side projections of the immutable report tree."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_hierarchy import validate_root_child
from .tree_paths import report_tree_paths
from .tree_store import load_head, load_node, tree_lock


def load_snapshot(*, package_root: Path, branch_id: str) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        head = load_head(paths)
        components: list[dict[str, Any]] = []
        bindings: list[dict[str, Any]] = []
        binding_ids: set[str] = set()
        flatten(
            paths, load_node(paths, head["root_ref"]), None,
            components, bindings, binding_ids,
        )
    return {
        "paths": paths,
        "head": head,
        "components": components,
        "bindings": bindings,
    }


def flatten(
    paths: dict[str, Path], node: dict[str, Any], parent_id: str | None,
    components: list[dict[str, Any]], bindings: list[dict[str, Any]],
    binding_ids: set[str],
) -> None:
    if node["kind"] != "root":
        if parent_id is None:
            validate_root_child(kind=node["kind"], parent_id="root")
        components.append({
            "component_id": node["node_id"], "kind": node["kind"],
            "parent_id": parent_id, "title": node["title"],
            "body": node["body"], "content": node["content"],
            "display_kind": node["display_kind"],
            "created_at": node["created_at"],
        })
        for item in node["bindings"]:
            if item["binding_id"] in binding_ids:
                raise ValueError("report tree has duplicate binding_id")
            binding_ids.add(item["binding_id"])
            bindings.append({**item, "component_id": node["node_id"]})
    for child in node["children"]:
        flatten(
            paths,
            load_node(paths, child["ref"]),
            None if node["kind"] == "root" else node["node_id"],
            components,
            bindings,
            binding_ids,
        )
