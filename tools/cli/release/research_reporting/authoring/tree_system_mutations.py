"""Trusted report-container mutations unavailable to public authoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_changes import append_binding
from .tree_hierarchy import validate_parent_child
from .tree_move import move_component
from .tree_conversion import convert_section_to_special
from .tree_navigation import node_path, rewrite
from .tree_paths import report_tree_paths
from .tree_replacement import replace_component
from .tree_removal import remove_component
from .tree_schema import validate_binding, validate_node
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


def promote_system_requirement_component(
    *, package_root: Path, branch_id: str, component_id: str,
    title: str, body: str, bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Convert reviewed requirement prose into its special in place."""
    paths = report_tree_paths(package_root, branch_id)
    additions = [validate_binding(item) for item in bindings]

    def change(
        paths, head, root, _pending, pending_bindings, displaced, created,
    ):
        nodes = node_path(
            paths, root, component_id, head["generation"],
        )[0]
        current = nodes[-1]
        if current["kind"] not in {"section", "subsection", "entry"}:
            raise ValueError(
                "requirement promotion needs an ordinary report section"
            )
        validate_parent_child(
            parent_kind=nodes[-2]["kind"], child_kind="special",
        )
        for child in current["children"]:
            child_kind = node_path(
                paths, root, child["node_id"], head["generation"],
            )[0][-1]["kind"]
            validate_parent_child(
                parent_kind="special", child_kind=child_kind,
            )
        changed: list[str] = []
        for binding in additions:
            head, root, binding_changed = append_binding(
                paths, head, root, component_id, binding,
                pending_bindings, displaced, created,
            )
            changed.extend(binding_changed)

        def transform(value: dict[str, Any]) -> dict[str, Any]:
            value["kind"] = "special"
            value["title"] = title
            value["display_kind"] = "obligation_requirement"
            value["body"] = body
            return validate_node(value)

        root, converted, replaced = rewrite(
            paths, root, component_id, head["generation"],
            transform, created=created,
        )
        displaced.update(replaced)
        return head, root, list(dict.fromkeys([*changed, *converted]))

    head = mutate(paths, change)
    return {"paths": paths, "head": head}
