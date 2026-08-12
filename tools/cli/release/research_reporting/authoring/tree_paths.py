"""Filesystem layout for the persistent branch report tree."""

from __future__ import annotations

from pathlib import Path

from ..package_layout import ensure_branch_report_tree
from .tree_schema import identifier


def report_tree_paths(package_root: Path, branch_id: str) -> dict[str, Path]:
    identifier(branch_id, "branch_id")
    branch_root = ensure_branch_report_tree(package_root, branch_id)
    root = branch_root / "authoring"
    return {
        "root": root,
        "head": root / "HEAD.json",
        "nodes": root / "nodes",
        "binding_registry": root / "binding-id-registry.jsonl",
        "index_db": root / "index.sqlite",
        "submission_db": root / "submission.sqlite",
        "pending_submission": root / "pending-submission.json",
        "lock": root / ".write.lock",
    }


def node_path(paths: dict[str, Path], node_id: str, node_hash: str) -> Path:
    identifier(node_id, "node_id")
    if len(node_hash) != 64:
        raise ValueError("node hash is invalid")
    return paths["nodes"] / node_hash[:2] / f"{node_hash}.json"
