"""Readable CLI failures for sequenced report submissions."""

from __future__ import annotations

import json
from typing import Any, NoReturn

import click

from tools.cli.release.research_reporting.authoring.submission_gate import (
    ReportSubmission,
    begin_submission,
    fail_submission,
)
from tools.cli.release.research_reporting.authoring.submission_pending import (
    load_pending,
)
from tools.cli.release.research_reporting.authoring.tree_paths import (
    report_tree_paths,
)
from .research_report_submission_blocked import SubmissionGateUsageError


def begin_or_raise(
    *,
    scope: Any,
    requested_sequence: int | None,
    logical_identity: dict[str, Any],
    payload: Any,
    as_json: bool,
) -> ReportSubmission:
    try:
        return begin_submission(
            package_root=scope.package_root,
            branch_id=scope.branch_id,
            requested_sequence=requested_sequence,
            logical_identity=logical_identity,
            payload=payload,
        )
    except ValueError as error:
        pending = current_pending(scope)
        raise SubmissionGateUsageError(
            str(error), as_json, pending=pending,
        ) from error


def reject_mutation(
    *,
    scope: Any,
    submission: ReportSubmission,
    error: Exception,
    as_json: bool,
) -> NoReturn:
    reject_submission(
        scope=scope,
        submission=submission,
        diagnostics=[{
            "component_id": "submission", "field": "operations",
            "line": 1, "column": 1,
            "code": "report.submission.invalid", "message": str(error),
            "rule": "修正同一逻辑提交后使用相同 submission_sequence 重新提交",
            "example": f"--submission-sequence {submission.sequence}",
        }],
        as_json=as_json,
    )


def reject_submission(
    *,
    scope: Any,
    submission: ReportSubmission,
    diagnostics: list[dict[str, Any]],
    as_json: bool,
) -> NoReturn:
    try:
        fail_submission(
            package_root=scope.package_root,
            branch_id=scope.branch_id,
            submission=submission,
            diagnostics=diagnostics,
        )
    except ValueError as error:
        raise_report_gate_error(scope=scope, error=error, as_json=as_json)
    raise SequencedSubmissionError(
        submission.sequence, submission.attempt, diagnostics, as_json,
    )


def current_pending(scope: Any) -> dict[str, Any] | None:
    return load_pending(report_tree_paths(
        scope.package_root, scope.branch_id,
    ))


def raise_report_gate_error(
    *, scope: Any, error: Exception, as_json: bool,
) -> NoReturn:
    pending = current_pending(scope)
    if pending is not None:
        raise SubmissionGateUsageError(
            str(error), as_json, pending=pending,
        ) from error
    raise click.ClickException(str(error)) from error


class SequencedSubmissionError(click.ClickException):
    def __init__(
        self, sequence: int, attempt: int,
        diagnostics: list[dict[str, Any]], as_json: bool,
    ) -> None:
        self.sequence, self.attempt, self.diagnostics, self.as_json = (
            sequence, attempt, diagnostics, as_json,
        )
        first = diagnostics[0]
        super().__init__(
            f"submission_sequence {sequence} 被拦截；"
            f"{first['component_id']} {first['field']} "
            f"{first['line']}:{first['column']} {first['message']}"
        )

    def show(self, file: Any = None) -> None:
        if self.as_json:
            click.echo(json.dumps({
                "status": "rejected",
                "submission_sequence": self.sequence,
                "attempt": self.attempt,
                "required_action": "correct_same_submission",
                "retry_option": f"--submission-sequence {self.sequence}",
                "diagnostics": self.diagnostics,
            }, ensure_ascii=False, sort_keys=True), file=file)
            return
        click.echo(
            f"Error: 报告提交 {self.sequence} 被拦截"
            f"（尝试 {self.attempt}）；"
            "只能修正该提交后使用相同序号重试",
            file=file,
        )
        for item in self.diagnostics:
            click.echo(
                f"- {item['component_id']}.{item['field']} "
                f"{item['line']}:{item['column']} [{item['code']}] "
                f"{item['message']}\n  规则：{item['rule']}\n"
                f"  示例：{item['example']}",
                file=file,
            )
