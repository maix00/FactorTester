"""Snapshot inheritance when one research Graph branch forks another."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .tree_paths import report_tree_paths
from .tree_store import load_head, tree_lock, write_head


def fork_report_tree(
    *,
    package_root: Path,
    source_branch_id: str,
    target_branch_id: str,
    target_report_id: str,
) -> dict[str, Any]:
    """Clone the source HEAD and immutable nodes into a new branch report."""
    if source_branch_id == target_branch_id:
        raise ValueError("report fork requires a distinct target branch")
    source = report_tree_paths(package_root, source_branch_id)
    target = report_tree_paths(package_root, target_branch_id)
    with tree_lock(source):
        source_head = load_head(source)
        with tree_lock(target):
            if target["head"].exists():
                raise ValueError("target branch report already exists")
            _copy_tree(source["nodes"], target["nodes"])
            _copy_tree(source["locators"], target["locators"])
            _copy_tree(
                source["binding_locators"],
                target["binding_locators"],
            )
            if source["binding_index"].is_file():
                target["binding_index"].parent.mkdir(
                    parents=True, exist_ok=True,
                )
                shutil.copy2(
                    source["binding_index"],
                    target["binding_index"],
                )
            head = {
                **source_head,
                "report_id": target_report_id,
                "changed_node_ids": ["root"],
            }
            write_head(target, head)
    return {"paths": target, "head": head}


def _copy_tree(source: Path, target: Path) -> None:
    if not source.is_dir():
        return
    shutil.copytree(source, target, dirs_exist_ok=True)
