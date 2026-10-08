"""Derived Markdown export for a branch-owned report tree."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..generation import publish_generation, report_workspace_lock
from ..git import commit_report_workspace
from ..package_layout import ensure_branch_report_tree
from .submission_status import require_no_pending
from .tree_paths import report_tree_paths
from .tree_projection import project_snapshot
from .tree_render import render_tree_markdown
from .tree_store import load_head, tree_lock


def export_branch_report(
    *, package_root: Path, report_workspace_id: str, branch_id: str,
    message: str = "Render branch research report", commit: bool = True,
) -> dict[str, Any]:
    """Materialize the current tree as a derived branch ``REPORT.md``.

    The tree ``HEAD`` is the sole content source.  This deliberately does not
    inspect or update retired package-wide indexes or report journals.
    """
    branch_root = ensure_branch_report_tree(package_root, branch_id)
    branch_path = branch_root / "REPORT.md"
    paths = report_tree_paths(package_root, branch_id)
    with report_workspace_lock(package_root):
        with tree_lock(paths):
            head = load_head(paths)
            require_no_pending(paths, head)
            snapshot = project_snapshot(paths, head)
            payload = render_tree_markdown(snapshot)
            content_hash = hashlib.sha256(payload).hexdigest()
            changed = publish_generation([("branch", branch_path, payload)])
            git = (
                commit_report_workspace(package_root, message=message)
                if commit else None
            )
    return {
        "path": branch_path,
        "changed": bool(changed["branch"]),
        "content_hash": content_hash,
        "git": git,
        "report_workspace_id": report_workspace_id,
        "branch_id": branch_id,
    }
