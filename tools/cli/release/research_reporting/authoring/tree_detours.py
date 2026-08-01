"""Persist the shared capability-detour operation plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .capability_detour_operation import capability_detour_operations
from .tree_model import apply_batch
from .tree_projection import load_snapshot


def ensure_capability_detour_special(
    *,
    package_root: Path,
    branch_id: str,
    parent_id: str,
    detour: dict[str, Any],
    current_node: str,
    latest_trace_id: str,
    component_id_hint: str = "",
) -> dict[str, Any]:
    snapshot = load_snapshot(
        package_root=package_root,
        branch_id=branch_id,
    )
    operations, component_id = capability_detour_operations(
        snapshot=snapshot,
        parent_id=parent_id,
        detour=detour,
        current_node=current_node,
        latest_trace_id=latest_trace_id,
        component_id_hint=component_id_hint,
    )
    saved = (
        apply_batch(
            package_root=package_root,
            branch_id=branch_id,
            operations=operations,
            include_snapshot=False,
        )
        if operations else {
            "paths": snapshot["paths"],
            "head": snapshot["head"],
            "components": [],
            "bindings": [],
        }
    )
    return {
        "changed": bool(operations),
        "component_id": component_id,
        "paths": saved["paths"],
        "head": saved["head"],
        "components": [],
        "bindings": [],
    }
