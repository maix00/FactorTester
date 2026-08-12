"""Read-only batch preflight before a report transaction creates nodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_assets import validate_asset
from .tree_batch_hierarchy import validate_hierarchy_plan
from .tree_batch_replacement import validate_replace
from .tree_hierarchy import validate_root_child
from .tree_locators import locator_exists
from .tree_navigation import contains_node
from .tree_schema import NODE_KINDS, identifier, validate_binding, validate_node


def validate_batch_operations(
    paths: dict[str, Path], head: dict[str, Any], root: dict[str, Any],
    operations: list[dict[str, Any]],
) -> None:
    validate_hierarchy_plan(paths, root, operations)
    added: set[str] = set()
    replaced: set[str] = set()
    bindings: set[str] = set()
    assets = {str(item["asset_ref"]) for item in head["assets"]}
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("report batch operation must be an object")
        op = operation.get("op")
        if op == "add":
            component_id, parent_id, items = _validate_add(operation)
            if component_id in added:
                raise ValueError("report batch duplicates component_id")
            if component_id == "root" or _exists(paths, head, root, component_id):
                raise ValueError("component_id already exists")
            if parent_id not in added and not _exists(paths, head, root, parent_id):
                raise ValueError("report component does not exist")
            added.add(component_id)
            _reserve_bindings(items, bindings)
        elif op == "replace":
            component_id, items = validate_replace(
                paths, head, root, operation,
            )
            if component_id in added or component_id in replaced:
                raise ValueError("report batch duplicates component_id")
            replaced.add(component_id)
            _reserve_bindings(items, bindings)
        elif op == "move":
            continue
        elif op == "bind":
            component_id = identifier(
                str(operation.get("component_id") or ""), "component_id"
            )
            if component_id not in added and not _exists(paths, head, root, component_id):
                raise ValueError("report component does not exist")
            _reserve_bindings([validate_binding(operation.get("binding"))], bindings)
        elif op == "asset":
            asset = validate_asset(operation.get("asset"))
            if asset["asset_ref"] in assets:
                raise ValueError("asset_ref already exists")
            assets.add(asset["asset_ref"])
        else:
            raise ValueError("unknown report batch operation")


def _validate_add(operation: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    component_id = identifier(str(operation.get("component_id") or ""), "component_id")
    kind = str(operation.get("kind") or "")
    if kind not in NODE_KINDS:
        raise ValueError("unsupported report component kind")
    parent = operation.get("parent_id")
    parent_id = "root" if parent is None else identifier(parent, "parent_id")
    validate_root_child(kind=kind, parent_id=parent_id)
    raw_bindings = operation.get("bindings") or []
    if not isinstance(raw_bindings, list):
        raise ValueError("report component bindings must be an array")
    bindings = [validate_binding(item) for item in raw_bindings]
    validate_node({
        "schema_version": 1, "node_id": component_id,
        "kind": kind,
        "title": str(operation.get("title") or ""),
        "body": str(operation.get("body") or ""),
        "content": operation.get("content"),
        "display_kind": str(operation.get("display_kind") or ""),
        "created_at": 0.0, "children": [], "bindings": bindings,
    })
    return component_id, parent_id, bindings


def _reserve_bindings(values: list[dict[str, Any]], seen: set[str]) -> None:
    for binding in values:
        binding_id = binding["binding_id"]
        if binding_id in seen:
            raise ValueError("report batch duplicates binding_id")
        seen.add(binding_id)


def _exists(
    paths: dict[str, Path], head: dict[str, Any], root: dict[str, Any], node_id: str,
) -> bool:
    if node_id == "root":
        return True
    indexed = locator_exists(paths, node_id, head["generation"])
    return bool(
        (indexed or head["locator_generation"] != head["generation"])
        and contains_node(paths, root, node_id)
    )
