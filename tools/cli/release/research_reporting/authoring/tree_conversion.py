"""Trusted conversion of a historical section into a special section."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_hierarchy import validate_parent_child
from .tree_navigation import node_path, rewrite
from .tree_schema import identifier


def convert_section_to_special(
    paths: dict[str, Path],
    head: dict[str, Any],
    root: dict[str, Any],
    component_id: str,
    display_kind: str,
    displaced: set[str],
    created: set[str],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    identifier(component_id, "component_id")
    nodes, edges = node_path(
        paths, root, component_id, head["generation"],
    )
    if not edges or nodes[-1]["kind"] != "section":
        raise ValueError(
            "special conversion requires one existing section"
        )
    parent = nodes[-2]
    validate_parent_child(
        parent_kind=parent["kind"], child_kind="special",
    )
    child_kinds = [
        node_path(
            paths, root, child["node_id"], head["generation"],
        )[0][-1]["kind"]
        for child in nodes[-1]["children"]
    ]
    for child_kind in child_kinds:
        validate_parent_child(
            parent_kind="special", child_kind=child_kind,
        )

    def transform(value: dict[str, Any]) -> dict[str, Any]:
        value["kind"] = "special"
        value["display_kind"] = display_kind
        return value

    rewritten, changed, replaced = rewrite(
        paths,
        root,
        component_id,
        head["generation"],
        transform,
        created=created,
    )
    displaced.update(replaced)
    return head, rewritten, changed
