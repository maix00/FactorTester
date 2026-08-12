"""Finalize a published report submission and expose resumable failures."""

from __future__ import annotations

from typing import Any

from tools.cli.release.research_reporting.authoring import (
    commit_branch_authoring,
)
from tools.cli.release.research_reporting.authoring.submission_finalize import (
    finalize_published_submission,
)

from .research_report_scope import persist_descriptor
from .research_report_submission_errors import raise_report_gate_error


class FinalizeStepError(RuntimeError):
    def __init__(self, stage: str, error: Exception) -> None:
        self.stage = stage
        super().__init__(str(error))


def finalize_report_command(
    *,
    scope: Any,
    submission: Any,
    descriptor: dict[str, Any],
    message: str,
    as_json: bool,
) -> dict[str, Any]:
    if submission.phase == "finalized":
        return dict(submission.finalize_result or {})

    def finalize() -> dict[str, Any]:
        try:
            persist_descriptor(scope, descriptor)
        except Exception as error:
            raise FinalizeStepError("descriptor", error) from error
        try:
            git = commit_branch_authoring(scope.package_root, message=message)
        except Exception as error:
            raise FinalizeStepError("git", error) from error
        return {"git": git}

    try:
        return finalize_published_submission(
            package_root=scope.package_root,
            branch_id=scope.branch_id,
            submission=submission,
            finalize=finalize,
        )
    except Exception as error:
        raise_report_gate_error(scope=scope, error=error, as_json=as_json)
