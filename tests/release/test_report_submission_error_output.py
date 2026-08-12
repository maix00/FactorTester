from __future__ import annotations

from io import StringIO
import json

from tools.cli.commands.research_report_submission_errors import (
    SubmissionGateUsageError,
)


def test_blocked_json_exposes_machine_readable_retry_contract() -> None:
    pending = {
        "submission_sequence": 13,
        "attempt": 2,
        "diagnostics": [{
            "component_id": "finding",
            "code": "report.math.invalid",
        }],
    }
    output = StringIO()

    SubmissionGateUsageError(
        "pending report submission requires submission_sequence 13",
        True,
        pending=pending,
    ).show(file=output)

    value = json.loads(output.getvalue())
    assert value["status"] == "blocked"
    assert value["submission_sequence"] == 13
    assert value["attempt"] == 2
    assert value["required_action"] == "correct_same_submission"
    assert value["retry_option"] == "--submission-sequence 13"
    assert value["diagnostics"] == pending["diagnostics"]
