"""Machine-readable output when another report submission owns the branch."""

from __future__ import annotations

import json
from typing import Any

import click


class SubmissionGateUsageError(click.ClickException):
    def __init__(
        self, message: str, as_json: bool,
        pending: dict[str, Any] | None = None,
    ) -> None:
        self.as_json, self.pending = as_json, pending
        super().__init__(message)

    def show(self, file: Any = None) -> None:
        if not self.as_json:
            super().show(file)
            if self.pending:
                sequence = self.pending["submission_sequence"]
                action = (
                    "使用完全相同的 payload 和序号重试收尾"
                    if self.pending.get("phase") == "published"
                    else "修正同一逻辑提交后使用相同序号重试"
                )
                click.echo(
                    f"Action: {action}：--submission-sequence {sequence}",
                    file=file,
                )
            return
        value: dict[str, Any] = {
            "status": "blocked", "message": self.message,
        }
        if self.pending:
            sequence = self.pending["submission_sequence"]
            published = self.pending.get("phase") == "published"
            value.update({
                "status": (
                    "published_pending_finalize" if published else "blocked"
                ),
                "submission_sequence": sequence,
                "attempt": self.pending["attempt"],
                "diagnostics": self.pending["diagnostics"],
                "required_action": (
                    "retry_same_submission_to_finalize"
                    if published else "correct_same_submission"
                ),
                "retry_option": f"--submission-sequence {sequence}",
            })
        click.echo(
            json.dumps(value, ensure_ascii=False, sort_keys=True),
            file=file,
        )
