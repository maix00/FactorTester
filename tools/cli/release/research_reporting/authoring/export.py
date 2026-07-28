"""Derived Markdown export for a branch-owned report tree."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..generation import publish_generation, work_package_lock
from ..git import commit_work_package
from ..package_layout import ensure_branch_report_tree
from .service import load_branch_authoring
from .tree_render import render_tree_markdown


def export_branch_report(
    *, package_root: Path, work_package_id: str, branch_id: str,
    message: str = "Render branch research report", commit: bool = True,
) -> dict[str, Any]:
    """Materialize the current tree as a derived branch ``REPORT.md``.

    The tree ``HEAD`` is the sole content source.  This deliberately does not
    inspect or update retired package-wide indexes or report journals.
    """
    branch_root = ensure_branch_report_tree(package_root, branch_id)
    branch_path = branch_root / "REPORT.md"
    with work_package_lock(package_root):
        snapshot = load_branch_authoring(
            package_root=package_root, branch_id=branch_id,
        )
        payload = render_tree_markdown(snapshot)
        content_hash = hashlib.sha256(payload).hexdigest()
        changed = publish_generation([("branch", branch_path, payload)])
        git = commit_work_package(package_root, message=message) if commit else None
    return {
        "path": branch_path,
        "changed": bool(changed["branch"]),
        "content_hash": content_hash,
        "git": git,
        "work_package_id": work_package_id,
        "branch_id": branch_id,
    }
