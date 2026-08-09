"""Read-side projections of the immutable report tree."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_hierarchy import validate_root_child
from .tree_paths import report_tree_paths
from .tree_store import load_head, load_node, tree_lock


def load_snapshot(*, package_root: Path, branch_id: str) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        head = load_head(paths)
        return project_snapshot(paths, head)


def load_report_index(*, package_root: Path, branch_id: str) -> dict[str, Any]:
    """Read report metadata and chapter headers without flattening the tree."""
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        head = load_head(paths)
        root = load_node(paths, head["root_ref"])
        chapters: list[dict[str, Any]] = []
        for child in root.get("children") or []:
            chapter = load_node(paths, child["ref"])
            if chapter.get("kind") != "chapter":
                continue
            first_child_title = ""
            for entry in chapter.get("children") or []:
                child_node = load_node(paths, entry["ref"])
                title = str(child_node.get("title") or "")
                if title:
                    first_child_title = title
                    break
            chapters.append({
                "component_id": chapter["node_id"],
                "title": str(chapter.get("title") or ""),
                "created_at": chapter.get("created_at"),
                "graph_version": chapter.get("graph_version"),
                "preview": first_child_title,
            })
        return {"paths": paths, "head": head, "chapter_descriptors": chapters}


def load_chapter_snapshot(
    *, package_root: Path, branch_id: str, chapter_id: str,
) -> dict[str, Any]:
    """Read one chapter subtree while holding the normal report lock."""
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        head = load_head(paths)
        root = load_node(paths, head["root_ref"])
        chapter_ref = next(
            (child["ref"] for child in root.get("children") or []
             if str(child.get("node_id") or "") == str(chapter_id)),
            None,
        )
        if chapter_ref is None:
            raise ValueError("report chapter was not found")
        chapter = load_node(paths, chapter_ref)
        if chapter.get("kind") != "chapter":
            raise ValueError("report chapter was not found")
        components: list[dict[str, Any]] = []
        bindings: list[dict[str, Any]] = []
        binding_ids: set[str] = set()
        flatten(paths, chapter, None, components, bindings, binding_ids)
        return {
            "paths": paths,
            "head": head,
            "components": components,
            "bindings": bindings,
        }


def project_snapshot(
    paths: dict[str, Path], head: dict[str, Any],
) -> dict[str, Any]:
    """Project a HEAD while the caller owns the report-tree lock."""
    components: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    binding_ids: set[str] = set()
    flatten(
        paths, load_node(paths, head["root_ref"]), None,
        components, bindings, binding_ids,
    )
    return {
        "paths": paths,
        "head": head,
        "components": components,
        "bindings": bindings,
    }


def flatten(
    paths: dict[str, Path], node: dict[str, Any], parent_id: str | None,
    components: list[dict[str, Any]], bindings: list[dict[str, Any]],
    binding_ids: set[str],
) -> None:
    if node["kind"] != "root":
        if parent_id is None:
            validate_root_child(kind=node["kind"], parent_id="root")
        components.append({
            "component_id": node["node_id"], "kind": node["kind"],
            "parent_id": parent_id, "title": node["title"],
            "body": node["body"], "content": node["content"],
            "display_kind": node["display_kind"],
            "created_at": node["created_at"],
        })
        for item in node["bindings"]:
            if item["binding_id"] in binding_ids:
                raise ValueError("report tree has duplicate binding_id")
            binding_ids.add(item["binding_id"])
            bindings.append({**item, "component_id": node["node_id"]})
    for child in node["children"]:
        flatten(
            paths,
            load_node(paths, child["ref"]),
            None if node["kind"] == "root" else node["node_id"],
            components,
            bindings,
            binding_ids,
        )
