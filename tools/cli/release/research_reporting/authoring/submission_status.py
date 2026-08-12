"""Read-side status and write barriers for pending report submissions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .submission_pending import reconcile_pending
from .tree_paths import report_tree_paths
from .tree_projection import project_snapshot
from .tree_store import load_head, tree_lock


def require_no_pending(
    paths: dict[str, Path], head: dict[str, Any],
) -> None:
    """Reject non-submission publication while a correction owns next HEAD."""
    pending = reconcile_pending(paths, head)
    if pending is None:
        return
    sequence = pending["submission_sequence"]
    raise ValueError(
        "report is blocked by pending submission_sequence "
        f"{sequence}; correct and retry it with --submission-sequence {sequence}"
    )


def load_reconciled_pending(
    *, package_root: Path, branch_id: str,
) -> dict[str, Any] | None:
    """Return current pending state, removing a stale post-publish marker."""
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        return reconcile_pending(paths, load_head(paths))


def load_authoring_status(
    *, package_root: Path, branch_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Atomically project current HEAD together with its reconciled lease."""
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        head = load_head(paths)
        pending = reconcile_pending(paths, head)
        return project_snapshot(paths, head), pending


def submission_status(
    pending: dict[str, Any] | None,
) -> dict[str, Any]:
    """Expose a compact, stable status suitable for CLI JSON."""
    if pending is None:
        return {
            "state": "ready",
            "writable": True,
            "submission_sequence": None,
            "attempt": None,
            "diagnostics": [],
        }
    return {
        "state": (
            "published_pending_finalize"
            if pending["phase"] == "published"
            else "blocked"
        ),
        "writable": False,
        "submission_sequence": pending["submission_sequence"],
        "attempt": pending["attempt"],
        "diagnostics": list(pending["diagnostics"]),
    }
