"""Public additive APIs for a branch-owned persistent report tree."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_assets import append_asset
from .tree_changes import append_binding, append_component
from .tree_operations import apply_operation
from .tree_agent_removal import validate_agent_removal
from .tree_removal import remove_component as _remove_component
from .tree_locators import locator_exists
from .tree_projection import load_snapshot
from .tree_paths import report_tree_paths
from .tree_schema import validate_binding
from .tree_store import (
    HEAD_SCHEMA_VERSION,
    load_head,
    store_node,
    tree_lock,
    write_head,
)
from .tree_sqlite_index import ensure_sqlite_index
from .tree_transactions import mutate, mutate_batch
from .submission_gate import ReportSubmission

MAX_BATCH_OPERATIONS = 256


def initialize_tree(
    *, package_root: Path, branch_id: str, report_id: str, title: str,
) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        if paths["head"].is_file():
            return {
                "paths": paths, "head": load_head(paths),
                "created": False, "upgraded": False,
            }
        root = {
            "schema_version": 1, "node_id": "root", "kind": "root",
            "title": "", "body": "", "content": None, "display_kind": "",
            "created_at": 0.0, "children": [], "bindings": [],
        }
        root_ref, _ = store_node(paths, root)
        head = {
            "schema_version": HEAD_SCHEMA_VERSION,
            "report_id": report_id, "title": title,
            "language": "zh-Hans", "generation": 0, "root_ref": root_ref,
            "assets": [], "changed_node_ids": ["root"],
            "locator_generation": 0,
        }
        write_head(paths, head)
        ensure_sqlite_index(paths, root, head["generation"])
    return {"paths": paths, "head": head, "created": True, "upgraded": False}


def add_component(
    *, package_root: Path, branch_id: str, component_id: str, kind: str,
    title: str, parent_id: str | None, body: str, content: Any,
    display_kind: str, bindings: list[dict[str, Any]] | None = None,
    before_component_id: str | None = None,
    after_component_id: str | None = None,
    include_snapshot: bool = True,
    submission: ReportSubmission | None = None,
) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    items = [validate_binding(item) for item in bindings or []]
    head = mutate(
        paths,
        lambda current, head, root, pending, pending_bindings, displaced, created: append_component(
            current, head, root, component_id, kind, title, parent_id, body,
            content, display_kind, items, before_component_id,
            after_component_id, pending, pending_bindings, displaced, created,
        ),
        submission=submission,
    )
    return _result(paths, head, package_root, branch_id, include_snapshot)


def add_binding(
    *, package_root: Path, branch_id: str, component_id: str,
    binding: dict[str, Any], include_snapshot: bool = True,
) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    item = validate_binding(binding)
    head = mutate(
        paths,
        lambda current, head, root, _pending, pending_bindings, displaced, created: append_binding(
            current, head, root, component_id, item, pending_bindings, displaced,
            created,
        ),
    )
    return _result(paths, head, package_root, branch_id, include_snapshot)


def add_asset(
    *, package_root: Path, branch_id: str, asset: dict[str, Any],
    include_snapshot: bool = True,
) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    head = mutate(
        paths,
        lambda _current, head, root, _pending, _pending_bindings, _displaced, _created: (
            append_asset(head, asset), root, ["root"],
        ),
    )
    return _result(paths, head, package_root, branch_id, include_snapshot)


def apply_batch(
    *, package_root: Path, branch_id: str, operations: list[dict[str, Any]],
    include_snapshot: bool = True,
    submission: ReportSubmission | None = None,
) -> dict[str, Any]:
    if (
        not isinstance(operations, list)
        or not operations
        or len(operations) > MAX_BATCH_OPERATIONS
    ):
        raise ValueError("report batch must contain 1 to 256 operations")
    paths = report_tree_paths(package_root, branch_id)
    head = mutate_batch(
        paths, operations, apply_operation, submission=submission,
    )
    return _result(paths, head, package_root, branch_id, include_snapshot)


def remove_component(
    *, package_root: Path, branch_id: str, component_id: str,
    include_children: bool, include_snapshot: bool = True,
    submission: ReportSubmission | None = None,
) -> dict[str, Any]:
    """Remove one Agent-authored ordinary component or ordinary subtree."""
    paths = report_tree_paths(package_root, branch_id)
    removed: list[str] = []

    def change(
        current, head, root, _pending, _bindings, displaced, created,
    ):
        removed.extend(validate_agent_removal(
            current, head, root, component_id,
            include_children=include_children,
        ))
        return _remove_component(
            current, head, root, component_id,
            allow_subtree=include_children,
            displaced=displaced, created=created,
        )

    head = mutate(paths, change, submission=submission)
    result = _result(
        paths, head, package_root, branch_id, include_snapshot,
    )
    result["removed_component_ids"] = removed
    return result


def _result(
    paths: dict[str, Path], head: dict[str, Any], package_root: Path,
    branch_id: str, include_snapshot: bool,
) -> dict[str, Any]:
    if include_snapshot:
        return load_snapshot(package_root=package_root, branch_id=branch_id)
    return {"paths": paths, "head": head, "components": [], "bindings": []}
