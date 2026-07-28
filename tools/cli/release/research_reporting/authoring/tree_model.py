"""Public additive APIs for a branch-owned persistent report tree."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .tree_changes import apply_operation, append_binding, append_component, replace_assets
from .tree_locators import locator_exists
from .tree_projection import load_snapshot
from .tree_paths import report_tree_paths
from .tree_schema import validate_binding
from .tree_store import load_head, store_node, tree_lock, write_head
from .tree_transactions import mutate, mutate_batch


def initialize_tree(
    *, package_root: Path, branch_id: str, report_id: str, title: str,
) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        if paths["head"].is_file():
            return {
                "paths": paths, "head": load_head(paths),
                "created": False, "upgraded": False,
            }
        root = {
            "schema_version": 1, "node_id": "root", "kind": "root",
            "title": "", "body": "", "content": None, "display_kind": "",
            "created_at": 0.0, "children": [], "bindings": [],
        }
        root_ref, _ = store_node(paths, root)
        head = {
            "schema_version": 2, "report_id": report_id, "title": title,
            "language": "zh-Hans", "generation": 0, "root_ref": root_ref,
            "assets": [], "changed_node_ids": ["root"],
            "locator_generation": 0,
        }
        write_head(paths, head)
    return {"paths": paths, "head": head, "created": True, "upgraded": False}


def add_component(
    *, package_root: Path, branch_id: str, component_id: str, kind: str,
    title: str, parent_id: str | None, body: str, content: Any,
    display_kind: str, bindings: list[dict[str, Any]] | None = None,
    include_snapshot: bool = True,
) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    items = [validate_binding(item) for item in bindings or []]
    head = mutate(
        paths,
        lambda current, head, root, pending, pending_bindings, displaced: append_component(
            current, head, root, component_id, kind, title, parent_id, body,
            content, display_kind, items, pending, pending_bindings, displaced,
        ),
    )
    return _result(paths, head, package_root, branch_id, include_snapshot)


def add_binding(
    *, package_root: Path, branch_id: str, component_id: str,
    binding: dict[str, Any], include_snapshot: bool = True,
) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    item = validate_binding(binding)
    head = mutate(
        paths,
        lambda current, head, root, _pending, pending_bindings, displaced: append_binding(
            current, head, root, component_id, item, pending_bindings, displaced,
        ),
    )
    return _result(paths, head, package_root, branch_id, include_snapshot)


def add_asset(
    *, package_root: Path, branch_id: str, asset: dict[str, Any],
    include_snapshot: bool = True,
) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    head = mutate(
        paths,
        lambda _current, head, root, _pending, _pending_bindings, _displaced: (
            replace_assets(head, asset), root, ["root"],
        ),
    )
    return _result(paths, head, package_root, branch_id, include_snapshot)


def apply_batch(
    *, package_root: Path, branch_id: str, operations: list[dict[str, Any]],
    include_snapshot: bool = True,
) -> dict[str, Any]:
    if not isinstance(operations, list) or not operations or len(operations) > 128:
        raise ValueError("report batch must contain 1 to 128 operations")
    paths = report_tree_paths(package_root, branch_id)
    head = mutate_batch(paths, operations, apply_operation)
    return _result(paths, head, package_root, branch_id, include_snapshot)


def ensure_node_chapter(
    *, package_root: Path, branch_id: str, node_id: str, title: str,
) -> dict[str, Any]:
    chapter_id = "chapter-" + _short_id(node_id)
    snapshot = load_snapshot(package_root=package_root, branch_id=branch_id)
    if locator_exists(snapshot["paths"], chapter_id, snapshot["head"]["generation"]):
        return {"changed": False, "component_id": chapter_id, **snapshot}
    added = add_component(
        package_root=package_root, branch_id=branch_id, component_id=chapter_id,
        kind="chapter", title=title, parent_id=None, body="", content=None,
        display_kind="", bindings=[{
            "binding_id": "chapter-node-" + _short_id(node_id),
            "kind": "graph_reference", "target_ref": f"node:{node_id}",
            "label": title,
            "data": {"role": "report_chapter", "chapter_ref": f"node:{node_id}"},
        }],
    )
    return {"changed": True, "component_id": chapter_id, **added}


def _short_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _result(
    paths: dict[str, Path], head: dict[str, Any], package_root: Path,
    branch_id: str, include_snapshot: bool,
) -> dict[str, Any]:
    if include_snapshot:
        return load_snapshot(package_root=package_root, branch_id=branch_id)
    return {"paths": paths, "head": head, "components": [], "bindings": []}
