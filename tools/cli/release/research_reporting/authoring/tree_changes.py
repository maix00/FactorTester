"""Validated additive changes used by report-tree transactions."""

from __future__ import annotations

import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from .tree_locators import locator_exists
from .tree_navigation import contains_node, rewrite
from .tree_schema import (
    identifier,
    validate_asset,
    validate_binding,
    validate_content,
    validate_node,
)
from .tree_store import store_node


def apply_operation(
    paths: dict[str, Path], head: dict[str, Any], root: dict[str, Any],
    operation: dict[str, Any], pending_locators: list[tuple[str, str]],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    if not isinstance(operation, dict):
        raise ValueError("report batch operation must be an object")
    op = operation.get("op")
    if op == "add":
        bindings = [validate_binding(item) for item in operation.get("bindings") or []]
        return append_component(
            paths, head, root, str(operation.get("component_id") or ""),
            str(operation.get("kind") or ""), str(operation.get("title") or ""),
            operation.get("parent_id"), str(operation.get("body") or ""),
            operation.get("content"), str(operation.get("display_kind") or ""),
            bindings, pending_locators,
        )
    if op == "chip":
        return append_binding(
            paths, head, root, str(operation.get("component_id") or ""),
            validate_binding(operation.get("binding")),
        )
    if op == "asset":
        return replace_assets(head, operation.get("asset")), root, ["root"]
    raise ValueError("unknown report batch operation")


def append_component(
    paths: dict[str, Path], head: dict[str, Any], root: dict[str, Any],
    component_id: str, kind: str, title: str, parent_id: str | None,
    body: str, content: Any, display_kind: str, bindings: list[dict[str, Any]],
    pending_locators: list[tuple[str, str]],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    identifier(component_id, "component_id")
    if kind not in {
        "chapter", "section", "subsection", "entry", "special", "table",
        "image", "code", "math", "result",
    }:
        raise ValueError("unsupported report component kind")
    validate_content(kind, content)
    indexed = locator_exists(paths, component_id, head["revision"])
    if indexed or (
        head["locator_revision"] != head["revision"]
        and contains_node(paths, root, component_id)
    ):
        raise ValueError("component_id already exists")
    node = new_node(component_id, kind, title, body, content, display_kind, bindings)
    ref, _ = store_node(paths, node)
    parent = "root" if parent_id is None else parent_id
    rewritten, changed = rewrite(
        paths,
        root,
        parent,
        head["revision"],
        lambda value: append_ref(value, component_id, ref),
    )
    pending_locators.append((component_id, parent))
    return head, rewritten, [*changed, component_id]


def append_binding(
    paths: dict[str, Path], head: dict[str, Any], root: dict[str, Any],
    component_id: str, binding: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    def mutate(value: dict[str, Any]) -> dict[str, Any]:
        if any(item["binding_id"] == binding["binding_id"] for item in value["bindings"]):
            raise ValueError("binding_id already exists")
        value["bindings"].append(binding)
        return value

    rewritten, changed = rewrite(
        paths, root, component_id, head["revision"], mutate,
    )
    return head, rewritten, [*changed, component_id]


def replace_assets(head: dict[str, Any], asset: Any) -> dict[str, Any]:
    value = validate_asset(asset)
    if any(item["asset_ref"] == value["asset_ref"] for item in head["assets"]):
        raise ValueError("asset_ref already exists")
    head["assets"].append(value)
    return head


def new_node(
    node_id: str, kind: str, title: str, body: str, content: Any,
    display_kind: str, bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    return validate_node({
        "schema_version": 1, "node_id": node_id, "kind": kind,
        "title": title, "body": body, "content": content,
        "display_kind": display_kind, "created_at": time.time(),
        "children": [], "bindings": bindings,
    })


def append_ref(node: dict[str, Any], component_id: str, ref: str) -> dict[str, Any]:
    node["children"].append({"node_id": component_id, "ref": ref})
    return node
