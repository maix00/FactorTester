"""Synchronize one declarative Graph report container locally."""

from __future__ import annotations

from typing import Any

from tools.cli.release.research_reporting.authoring.tree_descriptor import (
    report_tree_descriptor,
    section_refs_from_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_detours import (
    ensure_capability_detour_special,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    load_snapshot,
)
from tools.cli.release.research_reporting.git import commit_work_package

from .research_graph_local_report import (
    LocalGraphReport,
    persist_report_descriptor,
    synchronize_node_chapter,
)


def synchronize_report_container(
    scope: LocalGraphReport,
    *,
    container: dict[str, Any],
    component_hints: dict[str, str] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    anchor = str(container.get("anchor_node") or "")
    chapter = synchronize_node_chapter(
        scope, node_id=anchor, commit=commit,
    )
    if container.get("kind") == "chapter":
        return {
            **chapter,
            "container_kind": "chapter",
            "anchor_node": anchor,
        }
    if container.get("kind") != "special":
        raise ValueError("Graph report container kind is unsupported")
    detour = container.get("detour")
    if not isinstance(detour, dict):
        raise ValueError("special report container needs one capability detour")
    hints = component_hints or {}
    special = ensure_capability_detour_special(
        package_root=scope.package_root,
        branch_id=scope.branch_id,
        parent_id=str(chapter["component_id"]),
        detour=detour,
        current_node=str(container.get("current_node") or ""),
        latest_trace_id=str(detour.get("latest_trace_id") or ""),
        component_id_hint=str(hints.get(detour["episode_id"]) or ""),
    )
    git = (
        commit_work_package(
            scope.package_root,
            message="Synchronize capability detour report episode",
        )
        if commit else None
    )
    snapshot = load_snapshot(
        package_root=scope.package_root,
        branch_id=scope.branch_id,
    )
    descriptor = report_tree_descriptor(
        package_root=scope.package_root,
        work_package_id=scope.record["record_id"],
        branch_id=scope.branch_id,
        head=snapshot["head"],
        section_refs=section_refs_from_snapshot(snapshot),
    )
    persist_report_descriptor(scope, descriptor)
    return {
        "status": "synchronized",
        "container_kind": "special",
        "anchor_node": anchor,
        "node_id": str(container.get("current_node") or ""),
        "component_id": special["component_id"],
        "episode_component": {
            "episode_id": detour["episode_id"],
            "component_id": special["component_id"],
            "changed": special["changed"],
        },
        "created": [special["component_id"]] if special["changed"] else [],
        "existing": [] if special["changed"] else [special["component_id"]],
        "created_count": int(special["changed"]),
        "existing_count": int(not special["changed"]),
        "report_file": str(special["paths"]["head"]),
        "chapter_sync": chapter,
        "git": git,
    }
