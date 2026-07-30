"""Deterministic Graph-node chapter lookup without report-tree projection."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .tree_locators import locator_exists
from .tree_navigation import node_path
from .tree_paths import report_tree_paths
from .tree_store import load_head, load_node


def ensure_node_chapter(
    *, package_root: Path, branch_id: str, node_id: str, title: str,
) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    head = load_head(paths)
    existing = _bound_chapter(paths, head, node_id)
    if existing is not None:
        chapter_id, existing_title, chapter = existing
        if existing_title != title:
            from .tree_system_mutations import replace_system_component

            bindings = [
                {
                    **item,
                    "label": (
                        title
                        if item["kind"] == "graph_reference"
                        and item["target_ref"] == f"node:{node_id}"
                        and (item.get("data") or {}).get("role")
                        == "report_chapter"
                        else item["label"]
                    ),
                }
                for item in chapter["bindings"]
            ]
            replaced = replace_system_component(
                package_root=package_root,
                branch_id=branch_id,
                component={
                    "component_id": chapter_id,
                    "kind": chapter["kind"],
                    "title": title,
                    "body": chapter["body"],
                    "content": chapter["content"],
                    "display_kind": chapter["display_kind"],
                },
                bindings=bindings,
            )
            return _result(
                True, chapter_id,
                _chapter_section_ref(node_id, title, chapter_id),
                replaced["paths"], replaced["head"],
            )
        return _result(
            False, chapter_id,
            _chapter_section_ref(node_id, existing_title, chapter_id),
            paths, head,
        )
    chapter_id = "chapter-" + _short_id(node_id)
    exists = locator_exists(paths, chapter_id, head["generation"])
    if not exists and head["locator_generation"] != head["generation"]:
        root = load_node(paths, head["root_ref"])
        try:
            node_path(paths, root, chapter_id, head["generation"])
            exists = True
        except ValueError:
            pass
    section_ref = _chapter_section_ref(node_id, title, chapter_id)
    if exists:
        return _result(False, chapter_id, section_ref, paths, head)
    from .tree_model import add_component

    added = add_component(
        package_root=package_root, branch_id=branch_id, component_id=chapter_id,
        kind="chapter", title=title, parent_id=None, body="", content=None,
        display_kind="", bindings=[{
            "binding_id": "chapter-node-" + _short_id(node_id),
            "kind": "graph_reference", "target_ref": f"node:{node_id}",
            "label": title,
            "data": {"role": "report_chapter", "chapter_ref": f"node:{node_id}"},
        }], include_snapshot=False,
    )
    return _result(True, chapter_id, section_ref, added["paths"], added["head"])


def _bound_chapter(
    paths: dict[str, Path],
    head: dict[str, Any],
    node_id: str,
) -> tuple[str, str, dict[str, Any]] | None:
    root = load_node(paths, head["root_ref"])
    matches = []
    target_ref = f"node:{node_id}"
    for child in root["children"]:
        chapter = load_node(paths, child["ref"])
        if chapter["kind"] != "chapter":
            continue
        if any(
            binding["kind"] == "graph_reference"
            and binding["target_ref"] == target_ref
            and (binding.get("data") or {}).get("role") == "report_chapter"
            for binding in chapter["bindings"]
        ):
            matches.append((
                chapter["node_id"], chapter["title"], chapter,
            ))
    if len(matches) > 1:
        raise ValueError(
            f"multiple report chapters bind Graph node {node_id}"
        )
    return matches[0] if matches else None


def _result(
    changed: bool, component_id: str, section_ref: dict[str, str],
    paths: dict[str, Path], head: dict[str, Any],
) -> dict[str, Any]:
    return {
        "changed": changed, "component_id": component_id, "section_ref": section_ref,
        "paths": paths, "head": head, "components": [], "bindings": [],
    }


def _short_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _chapter_section_ref(node_id: str, title: str, chapter_id: str) -> dict[str, str]:
    return {
        "link_id": "chapter-node-" + _short_id(node_id),
        "kind": "report_section", "target_ref": f"node:{node_id}",
        "section_ref": chapter_id, "label": title,
    }
