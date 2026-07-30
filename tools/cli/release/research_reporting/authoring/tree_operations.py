"""Dispatch one validated report-tree batch operation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_assets import append_asset
from .tree_changes import append_binding, append_component
from .tree_move import move_component
from .tree_replacement import replace_component
from .tree_schema import validate_binding


def apply_operation(
    paths: dict[str, Path], head: dict[str, Any], root: dict[str, Any],
    operation: dict[str, Any], pending_locators: list[tuple[str, str]],
    pending_bindings: set[str], displaced: set[str], created: set[str],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    op = operation.get("op")
    if op == "add":
        bindings = [
            validate_binding(item) for item in operation.get("bindings") or []
        ]
        return append_component(
            paths, head, root, str(operation.get("component_id") or ""),
            str(operation.get("kind") or ""), str(operation.get("title") or ""),
            operation.get("parent_id"), str(operation.get("body") or ""),
            operation.get("content"), str(operation.get("display_kind") or ""),
            bindings, pending_locators, pending_bindings, displaced, created,
        )
    if op == "bind":
        return append_binding(
            paths, head, root, str(operation.get("component_id") or ""),
            validate_binding(operation.get("binding")), pending_bindings,
            displaced, created,
        )
    if op == "replace":
        return replace_component(
            paths, head, root, str(operation.get("component_id") or ""),
            str(operation.get("kind") or ""), str(operation.get("title") or ""),
            str(operation.get("body") or ""), operation.get("content"),
            str(operation.get("display_kind") or ""),
            [validate_binding(item) for item in operation.get("bindings") or []],
            pending_bindings, displaced, created,
            allow_binding_retarget=(
                operation.get("_trusted_binding_retarget") is True
            ),
        )
    if op == "move":
        return move_component(
            paths, head, root, str(operation.get("component_id") or ""),
            str(operation.get("parent_id") or "root"),
            operation.get("after_component_id"), pending_locators,
            displaced, created,
        )
    if op == "asset":
        return append_asset(head, operation.get("asset")), root, ["root"]
    raise ValueError("unknown report batch operation")
