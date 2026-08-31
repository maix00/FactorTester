"""High-leverage operations for one branch-owned report tree."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..git import commit_work_package
from ..work_package_identity import work_package_report_id
from .tree_descriptor import report_tree_descriptor, section_refs_from_snapshot
from .tree_model import (
    add_asset as _add_asset,
    add_binding as _add_binding,
    add_component as _add_component,
    apply_batch as _apply_batch,
    ensure_node_chapter,
    initialize_tree,
    load_snapshot,
    remove_component as _remove_component,
)
from .submission_gate import ReportSubmission
from ..node_titles import node_title_zh


def ensure_branch_authoring(*, package_root: Path, work_package_id: str, branch_id: str, title: str, branch_ref: str, node_id: str = "", commit: bool = True, materialize: bool = False) -> dict[str, Any]:
    """Initialize one report tree and create the current node chapter once."""
    initialized = initialize_tree(
        package_root=package_root, branch_id=branch_id,
        report_id=work_package_report_id(package_root, work_package_id), title=title,
    )
    chapter_sync = _unchanged()
    section_refs: list[dict[str, str]] = []
    if node_id:
        chapter = ensure_node_chapter(
            package_root=package_root, branch_id=branch_id, node_id=node_id,
            title=node_title_zh(node_id),
        )
        snapshot = (
            load_snapshot(package_root=package_root, branch_id=branch_id)
            if materialize else chapter
        )
        section_refs = [chapter["section_ref"]]
        chapter_sync = {
            "status": "synchronized", "created": [chapter["component_id"]] if chapter["changed"] else [],
            "existing": [] if chapter["changed"] else [chapter["component_id"]],
            "created_count": int(chapter["changed"]), "existing_count": int(not chapter["changed"]),
            "component_id": chapter["component_id"],
        }
    else:
        snapshot = (
            load_snapshot(package_root=package_root, branch_id=branch_id)
            if materialize else {
                "paths": initialized["paths"], "head": initialized["head"],
                "components": [], "bindings": [],
            }
        )
    git = commit_work_package(package_root, message="Initialize report tree") if commit and initialized["created"] else None
    return _result(
        package_root, work_package_id, branch_id, snapshot, chapter_sync, git,
        section_refs,
    )


def add_branch_component(*, package_root: Path, work_package_id: str, branch_id: str, component_id: str, kind: str, title: str, parent_id: str | None, body: str, content: Any, display_kind: str, bindings: list[dict[str, Any]] | None = None, before_component_id: str | None = None, after_component_id: str | None = None, materialize: bool = False, submission: ReportSubmission | None = None) -> dict[str, Any]:
    snapshot = _add_component(
        package_root=package_root, branch_id=branch_id, component_id=component_id,
        kind=kind, title=title, parent_id=parent_id, body=body, content=content,
        display_kind=display_kind, bindings=bindings,
        before_component_id=before_component_id,
        after_component_id=after_component_id,
        include_snapshot=materialize, submission=submission,
    )
    return _result(package_root, work_package_id, branch_id, snapshot, _unchanged(), None, [])


def attach_branch_binding(*, package_root: Path, work_package_id: str, branch_id: str, component_id: str, binding: dict[str, Any], materialize: bool = False) -> dict[str, Any]:
    snapshot = _add_binding(
        package_root=package_root, branch_id=branch_id, component_id=component_id,
        binding=binding, include_snapshot=materialize,
    )
    return _result(package_root, work_package_id, branch_id, snapshot, _unchanged(), None, [])


def register_branch_asset(*, package_root: Path, work_package_id: str, branch_id: str, asset: dict[str, Any], materialize: bool = False) -> dict[str, Any]:
    snapshot = _add_asset(package_root=package_root, branch_id=branch_id, asset=asset, include_snapshot=materialize)
    return _result(package_root, work_package_id, branch_id, snapshot, _unchanged(), None, [])


def apply_branch_batch(*, package_root: Path, work_package_id: str, branch_id: str, operations: list[dict[str, Any]], materialize: bool = False, submission: ReportSubmission | None = None) -> dict[str, Any]:
    snapshot = _apply_batch(
        package_root=package_root, branch_id=branch_id, operations=operations,
        include_snapshot=materialize, submission=submission,
    )
    return _result(package_root, work_package_id, branch_id, snapshot, _unchanged(), None, [])


def remove_branch_component(
    *, package_root: Path, work_package_id: str, branch_id: str,
    component_id: str, include_children: bool,
    materialize: bool = False,
    submission: ReportSubmission | None = None,
) -> dict[str, Any]:
    snapshot = _remove_component(
        package_root=package_root, branch_id=branch_id,
        component_id=component_id, include_children=include_children,
        include_snapshot=materialize, submission=submission,
    )
    removed = list(snapshot.pop("removed_component_ids"))
    result = _result(
        package_root, work_package_id, branch_id, snapshot,
        _unchanged(), None, [],
    )
    result["removed_component_ids"] = removed
    return result


def load_branch_authoring(*, package_root: Path, branch_id: str) -> dict[str, Any]:
    """Load only the committed HEAD revision; no legacy document fallback."""
    return load_snapshot(package_root=package_root, branch_id=branch_id)


def commit_branch_authoring(package_root: Path, *, message: str) -> dict[str, Any]:
    return commit_work_package(package_root, message=message)


def _result(package_root: Path, work_package_id: str, branch_id: str, snapshot: dict[str, Any], chapter_sync: dict[str, Any], git: dict[str, Any] | None, section_refs: list[dict[str, str]]) -> dict[str, Any]:
    refs = section_refs_from_snapshot(snapshot) if snapshot["components"] else section_refs
    return {
        "paths": snapshot["paths"], "head": snapshot["head"],
        "components": snapshot["components"], "bindings": snapshot["bindings"],
        "descriptor": report_tree_descriptor(
            package_root=package_root, work_package_id=work_package_id,
            branch_id=branch_id, head=snapshot["head"], section_refs=refs,
        ),
        "chapter_sync": chapter_sync, "git": git,
    }


def _unchanged() -> dict[str, Any]:
    return {"status": "synchronized", "created": [], "existing": [], "created_count": 0, "existing_count": 0}
