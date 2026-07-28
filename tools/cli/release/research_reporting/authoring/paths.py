"""Filesystem identities for branch-owned structured report sources."""

from __future__ import annotations

from pathlib import Path

from ..package_layout import ensure_branch_report_tree


DIRECTORY = "authoring"
DOCUMENT = "DOCUMENT.json"
BINDINGS = "BINDINGS.json"


def authoring_paths(package_root: Path, branch_id: str) -> dict[str, Path]:
    """Return the only structured report source for one local Graph branch."""
    branch_root = ensure_branch_report_tree(package_root, branch_id)
    root = branch_root / DIRECTORY
    return {
        "root": root,
        "document": root / DOCUMENT,
        "bindings": root / BINDINGS,
    }
