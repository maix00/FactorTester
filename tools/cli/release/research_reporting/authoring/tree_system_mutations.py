"""Trusted report-container mutations unavailable to public authoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_changes import append_component
from .tree_move import move_component
from .tree_conversion import convert_section_to_special
from .tree_navigation import node_path, rewrite
from .tree_paths import report_tree_paths
from .tree_replacement import replace_component
from .tree_removal import remove_component
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


def remove_system_component(
    *,
    package_root: Path,
    branch_id: str,
    component_id: str,
    allow_subtree: bool = False,
) -> dict[str, Any]:
    """Remove only a subtree already proven redundant by trusted migration."""
    paths = report_tree_paths(package_root, branch_id)

    def change(
        paths, head, root, _pending, _bindings, displaced, created,
    ):
        return remove_component(
            paths,
            head,
            root,
            component_id,
            allow_subtree=allow_subtree,
            displaced=displaced,
            created=created,
        )

    head = mutate(paths, change)
    return {"paths": paths, "head": head}


def convert_system_section_to_special(
    *,
    package_root: Path,
    branch_id: str,
    component_id: str,
    display_kind: str,
) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)

    def change(
        paths, head, root, _pending, _bindings, displaced, created,
    ):
        return convert_section_to_special(
            paths,
            head,
            root,
            component_id,
            display_kind,
            displaced,
            created,
        )

    head = mutate(paths, change)
    return {"paths": paths, "head": head}


def wrap_system_requirement_component(
    *,
    package_root: Path,
    branch_id: str,
    component_id: str,
    parent_id: str,
    after_component_id: str | None,
    wrapper: dict[str, Any],
    transferred_bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Atomically wrap historical requirement prose in its typed special.

    Existing workflow bindings are moved exactly. A pre-binding historical
    component may instead place an explicitly reviewed requirement binding on
    the new wrapper through ``wrapper.bindings``.
    """
    paths = report_tree_paths(package_root, branch_id)
    moved = [validate_binding(item) for item in transferred_bindings]
    moved_ids = {item["binding_id"] for item in moved}
    wrapper_bindings = [
        validate_binding(item) for item in wrapper.get("bindings") or []
    ]
    if not moved_ids and not wrapper_bindings:
        raise ValueError("historical requirement migration has no binding")

    def change(
        paths, head, root, pending, pending_bindings, displaced, created,
    ):
        source = node_path(
            paths, root, component_id, head["generation"],
        )[0]
        if len(source) < 2 or source[-2]["node_id"] != parent_id:
            raise ValueError(
                "historical requirement component parent changed"
            )
        head, root, changed_add = append_component(
            paths,
            head,
            root,
            str(wrapper["component_id"]),
            "special",
            str(wrapper["title"]),
            parent_id,
            str(wrapper.get("body") or ""),
            wrapper.get("content"),
            "obligation_requirement",
            wrapper_bindings,
            pending,
            pending_bindings,
            displaced,
            created,
        )
        head, root, changed_child = move_component(
            paths,
            head,
            root,
            component_id,
            str(wrapper["component_id"]),
            None,
            pending,
            displaced,
            created,
        )
        head, root, changed_position = move_component(
            paths,
            head,
            root,
            str(wrapper["component_id"]),
            parent_id,
            after_component_id,
            pending,
            displaced,
            created,
        )
        changed_remove: list[str] = []
        changed_bind: list[str] = []
        if moved:
            root, changed_remove, replaced_remove = rewrite(
                paths,
                root,
                component_id,
                head["generation"],
                lambda value: _without_bindings(value, moved_ids, moved),
                created=created,
            )
            displaced.update(replaced_remove)
            root, changed_bind, replaced_bind = rewrite(
                paths,
                root,
                str(wrapper["component_id"]),
                head["generation"],
                lambda value: _with_existing_bindings(value, moved),
                created=created,
            )
            displaced.update(replaced_bind)
        changed = list(dict.fromkeys([
            *changed_add,
            *changed_child,
            *changed_position,
            *changed_remove,
            *changed_bind,
        ]))
        return head, root, changed

    head = mutate(paths, change)
    return {"paths": paths, "head": head}


def _without_bindings(
    node: dict[str, Any],
    binding_ids: set[str],
    expected: list[dict[str, Any]],
) -> dict[str, Any]:
    matches = [
        item for item in node["bindings"]
        if item["binding_id"] in binding_ids
    ]
    if sorted(matches, key=lambda item: item["binding_id"]) != sorted(
        expected, key=lambda item: item["binding_id"],
    ):
        raise ValueError("historical requirement bindings changed")
    node["bindings"] = [
        item for item in node["bindings"]
        if item["binding_id"] not in binding_ids
    ]
    return node


def _with_existing_bindings(
    node: dict[str, Any],
    bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    existing = {item["binding_id"] for item in node["bindings"]}
    if existing & {item["binding_id"] for item in bindings}:
        raise ValueError("historical requirement binding already moved")
    node["bindings"].extend(bindings)
    return node
