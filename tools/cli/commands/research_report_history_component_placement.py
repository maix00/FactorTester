"""Chronological placement of server-referenced historical report items."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.cli.release.research_reporting.authoring.tree_system_mutations import (
    move_system_component,
)


def place_report_components(
    *,
    package_root: Path,
    branch_id: str,
    components: dict[str, dict[str, Any]],
    parent_by_component: dict[str, str],
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    unresolved = []
    for component_id, expected_parent in parent_by_component.items():
        component = components.get(component_id)
        if component is None:
            unresolved.append(f"report:{component_id}")
            continue
        if component["kind"] == "chapter":
            raise ValueError("historical report ref cannot relocate a chapter")
        if component_id == expected_parent:
            raise ValueError("historical report ref cannot parent itself")
        groups.setdefault(expected_parent, []).append(component_id)

    moved, existing = [], []
    for expected_parent, desired in groups.items():
        selected = set(desired)
        current = [
            component_id
            for component_id, component in components.items()
            if (
                component["parent_id"] == expected_parent
                and component_id in selected
            )
        ]
        parents_match = all(
            components[component_id]["parent_id"] == expected_parent
            for component_id in desired
        )
        if parents_match and current == desired:
            existing.extend(desired)
            continue
        for component_id in reversed(desired):
            move_system_component(
                package_root=package_root,
                branch_id=branch_id,
                component_id=component_id,
                parent_id=expected_parent,
            )
            components[component_id]["parent_id"] = expected_parent
        moved.extend(desired)
    return {
        "moved": moved,
        "existing": existing,
        "unresolved": unresolved,
    }
