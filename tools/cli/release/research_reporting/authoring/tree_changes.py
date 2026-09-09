"""Validated additive changes used by report-tree transactions."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .binding_index import binding_exists
from .tree_hierarchy import canonical_section_kind, validate_parent_child, validate_root_child
from .tree_locators import locator_exists
from .tree_navigation import contains_node, node_path, rewrite
from .tree_schema import (
    identifier,
    validate_content,
    validate_node,
)
from .tree_store import load_node, store_node


def append_component(
    paths: dict[str, Path], head: dict[str, Any], root: dict[str, Any],
    component_id: str, kind: str, title: str, parent_id: str | None,
    body: str, content: Any, display_kind: str, bindings: list[dict[str, Any]],
    before_component_id: str | None, after_component_id: str | None,
    pending_locators: list[tuple[str, str]], pending_bindings: set[str],
    displaced: set[str], created: set[str],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    identifier(component_id, "component_id")
    if component_id == "root":
        raise ValueError("component_id root is reserved")
    if kind not in {
        "chapter", "section", "subsection", "entry", "special", "list", "table",
        "image", "code", "math", "result",
    }:
        raise ValueError("unsupported report component kind")
    validate_content(kind, content)
    indexed = locator_exists(paths, component_id, head["generation"])
    if (
        indexed or head["locator_generation"] != head["generation"]
    ) and contains_node(paths, root, component_id):
        raise ValueError("component_id already exists")
    _reserve_binding_ids(
        paths, root, bindings, head["generation"], pending_bindings,
    )
    parent = "root" if parent_id is None else parent_id
    validate_root_child(kind=kind, parent_id=parent)
    parent_node = node_path(
        paths, root, parent, head["generation"],
    )[0][-1]
    validate_parent_child(
        parent_kind=parent_node["kind"], child_kind=kind,
    )
    node = new_node(component_id, kind, title, body, content, display_kind, bindings)
    ref, _ = store_node(paths, node, created=created)
    rewritten, changed, replaced = rewrite(
        paths,
        root,
        parent,
        head["generation"],
        lambda value: insert_ref(
            value, component_id, ref,
            before_component_id=before_component_id,
            after_component_id=after_component_id,
        ),
        created=created,
    )
    displaced.update(replaced)
    pending_locators.append((component_id, parent))
    return head, rewritten, [*changed, component_id]


def append_binding(
    paths: dict[str, Path], head: dict[str, Any], root: dict[str, Any],
    component_id: str, binding: dict[str, Any], pending_bindings: set[str],
    displaced: set[str], created: set[str],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    _reserve_binding_ids(
        paths, root, [binding], head["generation"], pending_bindings,
    )

    def mutate(value: dict[str, Any]) -> dict[str, Any]:
        if any(item["binding_id"] == binding["binding_id"] for item in value["bindings"]):
            raise ValueError("binding_id already exists")
        value["bindings"].append(binding)
        return value

    rewritten, changed, replaced = rewrite(
        paths, root, component_id, head["generation"], mutate, created=created,
    )
    displaced.update(replaced)
    return head, rewritten, [*changed, component_id]


def _reserve_binding_ids(
    paths: dict[str, Path], root: dict[str, Any],
    bindings: list[dict[str, Any]], generation: int, pending: set[str],
) -> None:
    for binding in bindings:
        binding_id = binding["binding_id"]
        indexed = binding_exists(paths, binding_id, generation)
        if binding_id in pending or (
            indexed and _contains_binding(paths, root, binding_id)
        ):
            raise ValueError("binding_id already exists")
        pending.add(binding_id)


def _contains_binding(
    paths: dict[str, Path], node: dict[str, Any], binding_id: str,
) -> bool:
    if any(item["binding_id"] == binding_id for item in node["bindings"]):
        return True
    return any(
        _contains_binding(paths, load_node(paths, child["ref"]), binding_id)
        for child in node["children"]
    )


def new_node(
    node_id: str, kind: str, title: str, body: str, content: Any,
    display_kind: str, bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    return validate_node({
        "schema_version": 1, "node_id": node_id, "kind": canonical_section_kind(kind),
        "title": title, "body": body, "content": content,
        "display_kind": display_kind, "created_at": time.time(),
        "children": [], "bindings": bindings,
    })


def insert_ref(
    node: dict[str, Any], component_id: str, ref: str, *,
    before_component_id: str | None, after_component_id: str | None,
) -> dict[str, Any]:
    if before_component_id is not None and after_component_id is not None:
        raise ValueError(
            "before_component_id and after_component_id are mutually exclusive"
        )
    child = {"node_id": component_id, "ref": ref}
    if before_component_id is not None:
        before = identifier(before_component_id, "before_component_id")
        matches = [
            index for index, item in enumerate(node["children"])
            if item["node_id"] == before
        ]
        if len(matches) != 1:
            raise ValueError("before_component_id must belong to the same parent")
        node["children"].insert(matches[0], child)
    elif after_component_id is not None:
        after = identifier(after_component_id, "after_component_id")
        matches = [
            index for index, item in enumerate(node["children"])
            if item["node_id"] == after
        ]
        if len(matches) != 1:
            raise ValueError("after_component_id must belong to the same parent")
        node["children"].insert(matches[0] + 1, child)
    else:
        node["children"].append(child)
    return node
