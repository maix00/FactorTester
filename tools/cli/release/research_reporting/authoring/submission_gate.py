"""Crash-consistent branch-local report submission sequencing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_paths import report_tree_paths
from .tree_store import load_head, tree_lock
from .submission_begin import begin_submission
from .submission_lease import ReportSubmission, matching_pending
from .submission_pending import (
    normalized_diagnostics,
    reconcile_pending,
    write_pending,
)
from .submission_finalize import reconcile_submission


def fail_submission(
    *,
    package_root: Path,
    branch_id: str,
    submission: ReportSubmission,
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist validation or mutation diagnostics without changing HEAD."""
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        head = load_head(paths)
        pending = reconcile_pending(paths, head)
        value = matching_pending(pending, submission)
        value = {
            **value,
            "phase": "rejected",
            "diagnostics": normalized_diagnostics(diagnostics),
        }
        write_pending(paths, value)
        return value


def validate_publish_lease(
    paths: dict[str, Path],
    head: dict[str, Any],
    submission: ReportSubmission | None,
) -> None:
    """Reject mutations that do not own the branch's pending generation."""
    pending = reconcile_pending(paths, head)
    if pending is None:
        if submission is not None:
            raise ValueError("report submission lease is no longer pending")
        return
    sequence = pending["submission_sequence"]
    if submission is None:
        raise ValueError(
            f"report is blocked by pending submission_sequence {sequence}"
        )
    matching_pending(pending, submission)
    if pending["phase"] == "published":
        raise ValueError("published report submission is awaiting finalization")
    if sequence != head["generation"] + 1:
        raise ValueError("pending report submission is not the next generation")
