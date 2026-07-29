"""One-time rich-text normalization for persisted report-tree components."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..authoring.tree_navigation import contains_node
from ..authoring.tree_paths import report_tree_paths
from ..authoring.tree_store import load_head, load_node, store_node, tree_lock
from ..authoring.tree_transactions import mutate
from .rich_text_nodes import normalize_node
from .rich_text_normalization import normalize_text


def inspect_rich_text_migration(
    *, package_root: Path, branch_id: str,
) -> dict[str, Any]:
    """Return the deterministic body/content changes without writing them."""
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        head = load_head(paths)
        root = load_node(paths, head["root_ref"])
        changes: list[dict[str, Any]] = []
        _inspect_node(paths, package_root, root, changes)
        return {
            "branch_id": branch_id,
            "generation": head["generation"],
            "change_count": len(changes),
            "changes": changes,
        }


def migrate_rich_text(
    *, package_root: Path, branch_id: str,
) -> dict[str, Any]:
    """Normalize all eligible text in one atomic report-tree generation."""
    paths = report_tree_paths(package_root, branch_id)
    changes: list[dict[str, Any]] = []
    try:
        head = mutate(
            paths,
            lambda *args: _apply_migration(
                *args, package_root=package_root, changes=changes,
            ),
        )
    except _NoMigration as stopped:
        return {
            "branch_id": branch_id, "migrated": False,
            "change_count": 0, "changes": [], "head": stopped.head,
        }
    return {
        "branch_id": branch_id, "migrated": True,
        "change_count": len(changes), "changes": changes, "head": head,
    }


def _apply_migration(
    paths: dict[str, Path], head: dict[str, Any], root: dict[str, Any],
    _pending_locators: list[tuple[str, str]], _pending_bindings: set[str],
    displaced: set[str], created: set[str], *,
    package_root: Path, changes: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    updated, changed_ids, changed = _rewrite_node(
        paths, package_root, root, changes, created, displaced,
    )
    if not changed:
        raise _NoMigration(head)
    if not contains_node(paths, updated, "root"):
        raise ValueError("rich-text migration produced an invalid report root")
    return head, updated, changed_ids


class _NoMigration(Exception):
    def __init__(self, head: dict[str, Any]) -> None:
        self.head = head


def _inspect_node(
    paths: dict[str, Path], package_root: Path, node: dict[str, Any],
    changes: list[dict[str, Any]],
) -> None:
    normalized, reasons = normalize_node(node, package_root)
    if normalized != node:
        changes.append({
            "component_id": node["node_id"],
            "reasons": reasons,
        })
    for child in node["children"]:
        _inspect_node(
            paths, package_root, load_node(paths, child["ref"]), changes,
        )


def _rewrite_node(
    paths: dict[str, Path], package_root: Path, node: dict[str, Any],
    changes: list[dict[str, Any]], created: set[str], displaced: set[str],
) -> tuple[dict[str, Any], list[str], bool]:
    updated, reasons = normalize_node(node, package_root)
    changed_ids: list[str] = []
    changed = updated != node
    if changed:
        changes.append({"component_id": node["node_id"], "reasons": reasons})
        changed_ids.append(node["node_id"])

    for index, child in enumerate(node["children"]):
        original = load_node(paths, child["ref"])
        rewritten, descendants, child_changed = _rewrite_node(
            paths, package_root, original, changes, created, displaced,
        )
        if not child_changed:
            continue
        child_ref, _ = store_node(paths, rewritten, created=created)
        displaced.add(child["ref"])
        updated["children"][index] = {
            "node_id": rewritten["node_id"], "ref": child_ref,
        }
        changed = True
        changed_ids.extend(descendants)

    if changed and node["node_id"] not in changed_ids:
        changed_ids.insert(0, node["node_id"])
    return updated, list(dict.fromkeys(changed_ids)), changed
