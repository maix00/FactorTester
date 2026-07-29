"""Two-phase publication finalization for one report submission."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .submission_lease import ReportSubmission, matching_pending
from .submission_pending import (
    load_pending,
    reconcile_pending,
    remove_pending,
    write_pending,
)
from .submission_receipts import (
    load_receipt,
    matching_receipt,
    write_receipt,
)
from .tree_paths import report_tree_paths
from .tree_store import load_head, tree_lock


def mark_submission_published(
    paths: dict[str, Path],
    *,
    submission: ReportSubmission | None,
    published_head: dict[str, Any],
) -> None:
    if submission is None:
        return
    pending = matching_pending(load_pending(paths), submission)
    if published_head["generation"] != submission.sequence:
        raise ValueError("published report generation does not match submission")
    write_pending(paths, {
        **pending,
        "phase": "published",
        "published_generation": submission.sequence,
        "published_root_ref": published_head["root_ref"],
        "diagnostics": [],
    })


def finalize_published_submission(
    *,
    package_root: Path,
    branch_id: str,
    submission: ReportSubmission,
    finalize: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Run descriptor/Git finalization once, then durably close the lease."""
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        head = load_head(paths)
        pending = reconcile_pending(paths, head)
        value = matching_pending(pending, submission)
        if value["phase"] != "published":
            raise ValueError("report submission content is not published")
        receipt = matching_receipt(
            load_receipt(paths, submission.sequence),
            sequence=submission.sequence,
            logical_digest=submission.logical_digest,
            payload_hash=submission.payload_hash,
        )
        if receipt is not None:
            _remove_or_confirm(paths)
            return receipt["finalize_result"]
        try:
            result = finalize()
        except Exception as error:
            write_pending(paths, {
                **value,
                "diagnostics": [_finalize_diagnostic(error, submission.sequence)],
            })
            raise
        if not isinstance(result, dict):
            raise ValueError("report submission finalize result must be an object")
        receipt = write_receipt(
            paths, submission=submission, head=head, finalize_result=result,
        )
        _remove_or_confirm(paths)
        return receipt["finalize_result"]


def reconcile_submission(*, package_root: Path, branch_id: str) -> bool:
    """Recover a post-HEAD crash as published-but-not-finalized state."""
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        before = load_pending(paths)
        after = reconcile_pending(paths, load_head(paths))
        return (
            before is not None
            and after is not None
            and before["phase"] != after["phase"]
        )


def _remove_or_confirm(paths: dict[str, Path]) -> None:
    try:
        remove_pending(paths)
    except OSError:
        if paths["pending_submission"].exists():
            raise


def _finalize_diagnostic(
    error: Exception, sequence: int,
) -> dict[str, Any]:
    stage = str(getattr(error, "stage", "") or "finalize")
    return {
        "component_id": "submission",
        "field": stage,
        "line": 1,
        "column": 1,
        "code": f"report.submission.{stage}_failed",
        "message": str(error),
        "rule": "使用同一提交序号和完全相同的 payload 重试收尾",
        "example": f"--submission-sequence {sequence}",
    }
