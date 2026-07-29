"""Trusted report-container mutations unavailable to public authoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_move import move_component
from .tree_paths import report_tree_paths
from .tree_replacement import replace_component
from .tree_schema import validate_binding
from .tree_transactions import mutate


def replace_system_component(
    *,
    package_root: Path,
    branch_id: str,
    component: dict[str, Any],
    bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    items = [
        validate_binding({
            key: value for key, value in item.items()
            if key != "component_id"
        }) for item in bindings
        if item["kind"] != "report_requirement"
    ]

    def change(
        paths, head, root, _pending, pending_bindings, displaced, created,
    ):
        return replace_component(
            paths, head, root, component["component_id"],
            component["kind"], component["title"], component["body"],
            component["content"], component["display_kind"], items,
            pending_bindings, displaced, created,
        )

    head = mutate(paths, change)
    return {"paths": paths, "head": head}


def move_system_component(
    *,
    package_root: Path,
    branch_id: str,
    component_id: str,
    parent_id: str,
) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)

    def change(
        paths, head, root, pending, _bindings, displaced, created,
    ):
        return move_component(
            paths, head, root, component_id, parent_id, None,
            pending, displaced, created,
        )

    head = mutate(paths, change)
    return {"paths": paths, "head": head}
