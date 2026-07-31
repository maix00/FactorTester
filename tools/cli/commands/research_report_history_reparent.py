"""Trusted relocation of checkpoint-bound historical report items."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.cli.release.research_reporting.authoring.tree_model import (
    load_snapshot,
)
from .research_report_history_component_placement import (
    place_report_components,
)


def reparent_checkpoint_items(
    *,
    package_root: Path,
    branch_id: str,
    parent_by_checkpoint: dict[str, str],
    parent_by_component: dict[str, str] | None = None,
) -> dict[str, Any]:
    explicit_parents = parent_by_component or {}
    snapshot = load_snapshot(
        package_root=package_root, branch_id=branch_id,
    )
    components = {
        item["component_id"]: item for item in snapshot["components"]
    }
    candidates: dict[str, list[str]] = {}
    for binding in snapshot["bindings"]:
        target = str(binding.get("target_ref") or "")
        component = components.get(str(binding.get("component_id") or ""))
        if (
            binding.get("kind") != "checkpoint"
            or target not in parent_by_checkpoint
            or (binding.get("data") or {}).get("role") == "checkpoint_receipt"
            or component is None
            or component["kind"] not in {"section", "special", "entry"}
            or component.get("display_kind") == "capability_detour"
        ):
            continue
        candidates.setdefault(target, []).append(component["component_id"])
    chronological_parents: dict[str, str] = {}
    unresolved = []
    for checkpoint_ref, expected_parent in parent_by_checkpoint.items():
        roots = _top_level(
            list(dict.fromkeys(candidates.get(checkpoint_ref) or [])),
            components,
        )
        if not roots:
            unresolved.append(checkpoint_ref)
            continue
        for component_id in roots:
            target_parent = explicit_parents.get(
                component_id, expected_parent,
            )
            previous = chronological_parents.setdefault(
                component_id, target_parent,
            )
            if previous != target_parent:
                raise ValueError(
                    "historical report component maps to multiple parents: "
                    f"report:{component_id}"
                )
    chronological_parents.update({
        component_id: parent_id
        for component_id, parent_id in explicit_parents.items()
        if component_id not in chronological_parents
    })
    report_placement = place_report_components(
        package_root=package_root,
        branch_id=branch_id,
        components=components,
        parent_by_component=chronological_parents,
    )
    return {
        "moved": report_placement["moved"],
        "existing": report_placement["existing"],
        "unresolved_checkpoint_refs": unresolved,
        "unresolved_report_refs": report_placement["unresolved"],
    }


def _top_level(
    component_ids: list[str],
    components: dict[str, dict[str, Any]],
) -> list[str]:
    selected = set(component_ids)
    roots = []
    for component_id in component_ids:
        parent = components[component_id]["parent_id"]
        seen = set()
        while parent:
            if parent in seen:
                raise ValueError("report hierarchy contains a parent cycle")
            seen.add(parent)
            if parent in selected:
                break
            parent = (
                components[parent]["parent_id"]
                if parent in components else None
            )
        else:
            roots.append(component_id)
    return roots
