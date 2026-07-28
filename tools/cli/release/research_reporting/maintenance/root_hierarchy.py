"""Repair the retired root-level content shape without a reader fallback."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..authoring.tree_compaction import prune_displaced_nodes
from ..authoring.tree_locators import write_locators
from ..authoring.tree_paths import report_tree_paths
from ..authoring.tree_store import (
    load_head,
    load_node,
    store_node,
    tree_lock,
    write_head,
)


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
    with tree_lock(paths):
        previous = load_head(paths)
        root = load_node(paths, previous["root_ref"])
        plan = _plan(paths, previous, root)
        if plan["status"] == "compliant":
            return {**plan, "migrated": False, "head": previous}
        if plan["status"] != "migratable":
            raise ValueError(
                "report root hierarchy is ambiguous; map legacy content explicitly"
            )

        target_id = str(plan["target_chapter_id"])
        top_nodes = _top_nodes(paths, root)
        target_ref, target = next(
            (ref, node) for ref, node in top_nodes if node["node_id"] == target_id
        )
        moved = [
            (ref, node) for ref, node in top_nodes if node["kind"] != "chapter"
        ]
        existing_ids = {child["node_id"] for child in target["children"]}
        moved_ids = [node["node_id"] for _, node in moved]
        if existing_ids.intersection(moved_ids):
            raise ValueError("report root hierarchy contains duplicate component IDs")

        created: set[str] = set()
        updated_chapter = deepcopy(target)
        updated_chapter["children"].extend({
            "node_id": node["node_id"], "ref": ref
        } for ref, node in moved)
        chapter_ref, _ = store_node(paths, updated_chapter, created=created)

        updated_root = deepcopy(root)
        updated_root["children"] = [
            {
                "node_id": node["node_id"],
                "ref": chapter_ref if node["node_id"] == target_id else ref,
            }
            for ref, node in top_nodes
            if node["kind"] == "chapter"
        ]
        root_ref, _ = store_node(paths, updated_root, created=created)
        generation = previous["generation"] + 1
        next_head = deepcopy(previous)
        next_head.update({
            "generation": generation,
            "root_ref": root_ref,
            "changed_node_ids": ["root", target_id, *moved_ids],
            "locator_generation": generation,
        })
        write_locators(
            paths, [(node_id, target_id) for node_id in moved_ids], generation,
        )
        write_head(paths, next_head)
        prune_displaced_nodes(
            paths, {previous["root_ref"], target_ref}, root_ref=root_ref,
        )
        return {
            **plan, "migrated": True, "moved_component_ids": moved_ids,
            "head": next_head,
        }


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
