"""One-time repair of legacy checkpoint chapter titles and binding kinds."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..authoring.tree_paths import report_tree_paths
from ..authoring.tree_store import (
    load_head,
    load_json,
    store_node,
    tree_lock,
    write_head,
)
from ..node_titles import node_title_zh
from .legacy_binding_kinds import normalized_legacy_binding_kind


def migrate_history_chapters(
    *, package_root: Path, branch_id: str,
    checkpoint_nodes: dict[str, str],
) -> dict[str, Any]:
    """Atomically rewrite one legacy tree from an authoritative checkpoint map."""
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        head = load_head(paths)
        changed: set[str] = set()
        renamed: list[dict[str, str]] = []
        normalized = 0
        missing: list[str] = []

        def rewrite(ref: str) -> tuple[str, dict[str, Any]]:
            nonlocal normalized
            node = load_json(paths["root"] / ref, label="历史报告节点")
            updated = deepcopy(node)
            children = []
            for child in node["children"]:
                child_ref, _ = rewrite(str(child["ref"]))
                children.append({**child, "ref": child_ref})
            updated["children"] = children
            for binding in updated["bindings"]:
                replacement = normalized_legacy_binding_kind(
                    str(binding["kind"]), str(binding["target_ref"]),
                )
                if replacement != binding["kind"]:
                    binding["kind"] = replacement
                    normalized += 1
                    changed.add(str(node["node_id"]))
            checkpoint = _legacy_checkpoint(updated)
            if checkpoint:
                node_id = checkpoint_nodes.get(checkpoint)
                if not node_id:
                    missing.append(checkpoint)
                else:
                    title = node_title_zh(node_id)
                    if updated["title"] != title:
                        renamed.append({
                            "component_id": str(node["node_id"]),
                            "checkpoint_ref": checkpoint,
                            "node_id": node_id,
                            "title": title,
                        })
                        updated["title"] = title
                        changed.add(str(node["node_id"]))
            new_ref, _ = store_node(paths, updated)
            if new_ref != ref:
                changed.add(str(node["node_id"]))
            return new_ref, updated

        root_ref, _ = rewrite(head["root_ref"])
        if missing:
            raise ValueError(
                "historical checkpoint node mapping is incomplete: "
                + ", ".join(sorted(set(missing)))
            )
        if not changed:
            return _result(head, renamed, normalized, False)
        next_head = {
            **head,
            "generation": head["generation"] + 1,
            "root_ref": root_ref,
            "changed_node_ids": sorted(changed),
        }
        write_head(paths, next_head)
    return _result(next_head, renamed, normalized, True)


def _legacy_checkpoint(node: dict[str, Any]) -> str:
    if (
        node.get("kind") != "chapter"
        or not str(node.get("title") or "").startswith("历史检查点 ")
    ):
        return ""
    targets = {
        str(item.get("target_ref") or "")
        for item in node.get("bindings") or []
        if item.get("kind") == "checkpoint"
    }
    if len(targets) != 1:
        raise ValueError("legacy checkpoint chapter must bind exactly one checkpoint")
    return targets.pop()


def _result(
    head: dict[str, Any], renamed: list[dict[str, str]],
    normalized: int, migrated: bool,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "migrated": migrated,
        "generation": head["generation"],
        "renamed_count": len(renamed),
        "renamed": renamed,
        "normalized_binding_count": normalized,
    }
