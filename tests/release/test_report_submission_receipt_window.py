from __future__ import annotations

import json

from click.testing import CliRunner

from tests.release.test_report_submission_cli import _args, _scope
from tools.cli.commands import (
    research_report_authoring,
    research_report_component,
    research_report_inspection,
)
from tools.cli.commands.research_report import report as report_cli


def test_only_current_head_generation_can_replay_finalized_receipt(
    tmp_path, monkeypatch,
) -> None:
    client_root, _workspace_root = _scope(tmp_path)
    for module in (
        research_report_authoring,
        research_report_component,
        research_report_inspection,
    ):
        monkeypatch.setattr(
            module, "load_profile_root", lambda _path: client_root,
        )
    runner = CliRunner()
    first = [
        "add", *_args(), "--component-id", "first", "--kind", "chapter",
        "--title", "第一代", "--body", "正文一", "--json",
    ]
    second = [
        "add", *_args(), "--component-id", "second", "--kind", "chapter",
        "--title", "第二代", "--body", "正文二", "--json",
    ]
    assert runner.invoke(report_cli, first).exit_code == 0
    assert runner.invoke(report_cli, second).exit_code == 0

    stale = runner.invoke(
        report_cli, [*first[:-1], "--submission-sequence", "1", "--json"],
    )

    assert stale.exit_code == 1
    value = json.loads(stale.output)
    assert value["status"] == "blocked"
    assert "must be 3" in value["message"]
