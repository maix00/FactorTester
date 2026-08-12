"""Repair branch reports that were migrated without inherited ancestors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..authoring.tree_model import (
    add_asset,
    apply_batch,
    load_snapshot,
)
from ..authoring.tree_paths import report_tree_paths
from ..authoring.tree_transactions import mutate


def prepend_branch_snapshot(
    *,
    package_root: Path,
    source_branch_id: str,
    target_branch_id: str,
) -> dict[str, Any]:
    """Prepend one ancestor snapshot while preserving typed components."""
    source = load_snapshot(
        package_root=package_root, branch_id=source_branch_id,
    )
    target = load_snapshot(
        package_root=package_root, branch_id=target_branch_id,
    )
    target_components = {
        item["component_id"]: item for item in target["components"]
    }
    source_bindings = _bindings_by_component(source["bindings"])
    target_bindings = {
        item["binding_id"]: item for item in target["bindings"]
    }
    _require_compatible_assets(source, target)
    operations: list[dict[str, Any]] = []
    added_binding_ids: list[str] = []
    for component in source["components"]:
        existing = target_components.get(component["component_id"])
        if existing is not None:
            _require_same_component(component, existing)
            for binding in source_bindings.get(component["component_id"], []):
                normalized = {**binding, "component_id": component["component_id"]}
                current = target_bindings.get(binding["binding_id"])
                if current is not None and current != normalized:
                    raise ValueError(
                        "inherited report binding conflicts with target"
                    )
                if current is None:
                    operations.append({
                        "op": "bind",
                        "component_id": component["component_id"],
                        "binding": binding,
                    })
                    added_binding_ids.append(binding["binding_id"])
            continue
        operations.append({
            "op": "add",
            **{
                key: component[key]
                for key in (
                    "component_id", "kind", "title", "parent_id", "body",
                    "content", "display_kind",
                )
            },
            "bindings": source_bindings.get(component["component_id"], []),
        })
        added_binding_ids += [
            item["binding_id"]
            for item in source_bindings.get(component["component_id"], [])
        ]
    for chunk in _chunks(operations, 128):
        apply_batch(
            package_root=package_root,
            branch_id=target_branch_id,
            operations=chunk,
            include_snapshot=False,
        )
    _merge_assets(package_root, source, target_branch_id)
    prefix = [
        item["component_id"] for item in source["components"]
        if item["parent_id"] is None
    ]
    _prepend_root(
        package_root=package_root,
        branch_id=target_branch_id,
        component_ids=prefix,
    )
    result = load_snapshot(
        package_root=package_root, branch_id=target_branch_id,
    )
    return {
        "source_branch_id": source_branch_id,
        "target_branch_id": target_branch_id,
        "added_component_ids": [
            item["component_id"] for item in source["components"]
            if item["component_id"] not in target_components
        ],
        "added_binding_ids": added_binding_ids,
        "snapshot": result,
    }


def _bindings_by_component(
    bindings: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for binding in bindings:
        value = {
            key: value for key, value in binding.items()
            if key != "component_id"
        }
        result.setdefault(binding["component_id"], []).append(value)
    return result


def _require_same_component(
    source: dict[str, Any], target: dict[str, Any],
) -> None:
    fields = (
        "kind", "title", "parent_id", "body", "content", "display_kind",
    )
    if any(source[field] != target[field] for field in fields):
        raise ValueError("inherited report component conflicts with target")


def _chunks(
    values: list[dict[str, Any]], size: int,
) -> list[list[dict[str, Any]]]:
    return [
        values[index:index + size]
        for index in range(0, len(values), size)
    ]


def _merge_assets(
    package_root: Path, source: dict[str, Any], target_branch_id: str,
) -> None:
    current = load_snapshot(
        package_root=package_root, branch_id=target_branch_id,
    )
    assets = {
        item["asset_ref"]: item for item in current["head"]["assets"]
    }
    for asset in source["head"]["assets"]:
        existing = assets.get(asset["asset_ref"])
        if existing is not None and existing != asset:
            raise ValueError("inherited report asset conflicts with target")
        if existing is None:
            add_asset(
                package_root=package_root, branch_id=target_branch_id,
                asset=asset, include_snapshot=False,
            )


def _require_compatible_assets(
    source: dict[str, Any], target: dict[str, Any],
) -> None:
    current = {
        item["asset_ref"]: item for item in target["head"]["assets"]
    }
    for asset in source["head"]["assets"]:
        existing = current.get(asset["asset_ref"])
        if existing is not None and existing != asset:
            raise ValueError("inherited report asset conflicts with target")


def _prepend_root(
    *, package_root: Path, branch_id: str, component_ids: list[str],
) -> None:
    snapshot = load_snapshot(
        package_root=package_root, branch_id=branch_id,
    )
    current_ids = [
        item["component_id"] for item in snapshot["components"]
        if item["parent_id"] is None
    ]
    expected_ids = component_ids + [
        item for item in current_ids if item not in component_ids
    ]
    if current_ids == expected_ids:
        return
    paths = report_tree_paths(package_root, branch_id)

    def change(current, head, root, *_state):
        by_id = {item["node_id"]: item for item in root["children"]}
        if any(item not in by_id for item in component_ids):
            raise ValueError("inherited report chapter is missing")
        remaining = [
            item for item in root["children"]
            if item["node_id"] not in component_ids
        ]
        root["children"] = [
            by_id[item] for item in component_ids
        ] + remaining
        return head, root, ["root"]

    mutate(paths, change)
