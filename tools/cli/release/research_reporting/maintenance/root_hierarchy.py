"""Repair the retired root-level content shape without a reader fallback."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..authoring.tree_paths import report_tree_paths
from ..authoring.tree_store import (
    load_head,
    load_node,
    store_node,
    tree_lock,
)
from ..authoring.tree_transactions import mutate


def inspect_root_hierarchy(*, package_root: Path, branch_id: str) -> dict[str, Any]:
    """Classify a branch without modifying it."""
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        head = load_head(paths)
        root = load_node(paths, head["root_ref"])
        return _plan(paths, head, root)


def migrate_single_chapter_root(
    *, package_root: Path, branch_id: str,
) -> dict[str, Any]:
    """Move root-level content under the only root chapter atomically."""
    paths = report_tree_paths(package_root, branch_id)
    captured: dict[str, Any] = {}
    try:
        head = mutate(
            paths,
            lambda *args: _apply_migration(*args, captured=captured),
        )
    except _NoMigration as stopped:
        return {**stopped.plan, "migrated": False, "head": stopped.head}
    return {
        **captured["plan"], "migrated": True,
        "moved_component_ids": captured["moved_ids"], "head": head,
    }


def _apply_migration(
    paths: dict[str, Path], head: dict[str, Any], root: dict[str, Any],
    pending_locators: list[tuple[str, str]], _pending_bindings: set[str],
    displaced: set[str], created: set[str], *, captured: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    plan = _plan(paths, head, root)
    if plan["status"] == "compliant":
        raise _NoMigration(plan, head)
    if plan["status"] != "migratable":
        raise ValueError(
            "report root hierarchy is ambiguous; map legacy content explicitly"
        )
    target_id = str(plan["target_chapter_id"])
    top_nodes = _top_nodes(paths, root)
    target_ref, target = next(
        (ref, node) for ref, node in top_nodes if node["node_id"] == target_id
    )
    moved = [(ref, node) for ref, node in top_nodes if node["kind"] != "chapter"]
    moved_ids = [node["node_id"] for _, node in moved]
    if {child["node_id"] for child in target["children"]}.intersection(moved_ids):
        raise ValueError("report root hierarchy contains duplicate component IDs")
    updated_chapter = deepcopy(target)
    updated_chapter["children"].extend(
        {"node_id": node["node_id"], "ref": ref} for ref, node in moved
    )
    chapter_ref, _ = store_node(paths, updated_chapter, created=created)
    updated_root = deepcopy(root)
    updated_root["children"] = [{
        "node_id": node["node_id"],
        "ref": chapter_ref if node["node_id"] == target_id else ref,
    } for ref, node in top_nodes if node["kind"] == "chapter"]
    pending_locators.extend((node_id, target_id) for node_id in moved_ids)
    displaced.update({head["root_ref"], target_ref})
    captured.update({"plan": plan, "moved_ids": moved_ids})
    return deepcopy(head), updated_root, ["root", target_id, *moved_ids]


class _NoMigration(Exception):
    def __init__(self, plan: dict[str, Any], head: dict[str, Any]) -> None:
        self.plan = plan
        self.head = head


def _plan(
    paths: dict[str, Path], head: dict[str, Any], root: dict[str, Any],
) -> dict[str, Any]:
    top_nodes = _top_nodes(paths, root)
    chapters = [node for _, node in top_nodes if node["kind"] == "chapter"]
    non_chapters = [node for _, node in top_nodes if node["kind"] != "chapter"]
    if not non_chapters:
        status = "compliant"
        target = ""
    elif len(chapters) == 1:
        status = "migratable"
        target = chapters[0]["node_id"]
    else:
        status = "ambiguous"
        target = ""
    return {
        "status": status, "branch_id": str(head["report_id"]),
        "generation": head["generation"],
        "root_chapter_ids": [node["node_id"] for node in chapters],
        "root_content_ids": [node["node_id"] for node in non_chapters],
        "target_chapter_id": target,
    }


def _top_nodes(
    paths: dict[str, Path], root: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    return [
        (child["ref"], load_node(paths, child["ref"]))
        for child in root["children"]
    ]
