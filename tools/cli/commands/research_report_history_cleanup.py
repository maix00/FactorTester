"""Collapse legacy checkpoint chapters into canonical Graph chapters."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from tools.cli.release.research_reporting.authoring.tree_model import (
    load_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_system_mutations import (
    move_system_component,
    remove_system_component,
)


def cleanup_legacy_chapters(
    *,
    package_root: Path,
    branch_id: str,
    canonical_component_ids: set[str],
) -> dict[str, list[str]]:
    snapshot = load_snapshot(
        package_root=package_root, branch_id=branch_id,
    )
    components = snapshot["components"]
    by_id = {
        str(item["component_id"]): item for item in components
    }
    children = _children(components)
    bindings = _bindings(snapshot["bindings"])
    roots = [item for item in components if item["parent_id"] is None]
    canonical = [
        item for item in roots
        if item["component_id"] in canonical_component_ids
    ]
    canonical_by_title = _unique_titles(canonical)
    legacy = [
        item for item in roots
        if item["component_id"] not in canonical_component_ids
    ]

    removed_duplicates: list[str] = []
    moved: list[str] = []
    for title, target in canonical_by_title.items():
        matching_roots = [
            item for item in roots if item["title"] == title
        ]
        candidates = [
            child
            for root in matching_roots
            for child in children.get(root["component_id"], [])
        ]
        duplicate_ids = _redundant_ids(
            candidates, children=children, bindings=bindings,
        )
        for component_id in duplicate_ids:
            remove_system_component(
                package_root=package_root,
                branch_id=branch_id,
                component_id=component_id,
                allow_subtree=True,
            )
            removed_duplicates.append(component_id)
        desired = [
            item["component_id"] for item in candidates
            if (
                item["component_id"] not in duplicate_ids
                and item["parent_id"] != target["component_id"]
            )
        ]
        for component_id in reversed(desired):
            move_system_component(
                package_root=package_root,
                branch_id=branch_id,
                component_id=component_id,
                parent_id=target["component_id"],
            )
        moved.extend(desired)

    refreshed = load_snapshot(
        package_root=package_root, branch_id=branch_id,
    )
    refreshed_children = _children(refreshed["components"])
    removed_chapters: list[str] = []
    unresolved: list[str] = []
    for chapter in legacy:
        component_id = chapter["component_id"]
        if refreshed_children.get(component_id):
            unresolved.append(component_id)
            continue
        remove_system_component(
            package_root=package_root,
            branch_id=branch_id,
            component_id=component_id,
        )
        removed_chapters.append(component_id)
    return {
        "moved": moved,
        "removed_duplicates": removed_duplicates,
        "removed_legacy_chapters": removed_chapters,
        "unresolved_legacy_chapters": unresolved,
    }


def _unique_titles(
    components: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for component in components:
        grouped[str(component["title"])].append(component)
    duplicates = [title for title, items in grouped.items() if len(items) != 1]
    if duplicates:
        raise ValueError(
            "canonical Graph chapters have duplicate titles: "
            + ", ".join(sorted(duplicates))
        )
    return {title: items[0] for title, items in grouped.items()}


def _children(
    components: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for component in components:
        parent = component.get("parent_id")
        if parent is not None:
            result[str(parent)].append(component)
    return result


def _bindings(
    values: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for value in values:
        result[str(value["component_id"])].append(value)
    return result


def _redundant_ids(
    components: list[dict[str, Any]],
    *,
    children: dict[str, list[dict[str, Any]]],
    bindings: dict[str, list[dict[str, Any]]],
) -> set[str]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for component in components:
        groups[_semantic_tree(component, children)].append(component)
    redundant: set[str] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        coverage = {
            item["component_id"]: _binding_semantics(
                item, children=children, bindings=bindings,
            )
            for item in group
        }
        union = set().union(*coverage.values())
        survivors = [
            item for item in group
            if coverage[item["component_id"]] >= union
        ]
        if not survivors:
            continue
        survivor = survivors[0]["component_id"]
        redundant.update(
            item["component_id"] for item in group
            if item["component_id"] != survivor
        )
    return redundant


def _semantic_tree(
    component: dict[str, Any],
    children: dict[str, list[dict[str, Any]]],
) -> str:
    value = [
        component["kind"], component["title"], component["body"],
        component["content"], component["display_kind"],
        [
            _semantic_tree(child, children)
            for child in children.get(component["component_id"], [])
        ],
    ]
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def _binding_semantics(
    component: dict[str, Any],
    *,
    children: dict[str, list[dict[str, Any]]],
    bindings: dict[str, list[dict[str, Any]]],
    path: tuple[int, ...] = (),
) -> set[str]:
    result = {
        json.dumps(
            [
                path, item["kind"], item["target_ref"],
                item["label"], item["data"],
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for item in bindings.get(component["component_id"], [])
    }
    for index, child in enumerate(
        children.get(component["component_id"], [])
    ):
        result.update(_binding_semantics(
            child,
            children=children,
            bindings=bindings,
            path=(*path, index),
        ))
    return result
