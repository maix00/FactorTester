from __future__ import annotations

import json

from click.testing import CliRunner

from tests.release.test_report_submission_cli import _args, _scope
from tools.cli.commands import (
    research_report_authoring,
    research_report_component,
    research_report_inspection,
    research_report_submission,
)
from tools.cli.commands.research_report import report as report_cli
from tools.cli.commands.research_report_submission_identity import (
    component_identity,
)
from tools.cli.release.research_reporting.authoring.submission_gate import (
    begin_submission,
)


def _patch_root(monkeypatch, client_root) -> None:
    for module in (
        research_report_authoring,
        research_report_component,
        research_report_inspection,
    ):
        monkeypatch.setattr(
            module, "load_profile_root", lambda _path: client_root,
        )


def _reject_once(runner: CliRunner) -> None:
    rejected = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "finding", "--kind", "chapter",
        "--title", "结论", "--body", r"错误 \(", "--json",
    ])
    assert rejected.exit_code == 1
    assert json.loads(rejected.output)["submission_sequence"] == 1


def test_superseded_retry_returns_current_structured_gate(
    tmp_path, monkeypatch,
) -> None:
    client_root, _workspace_root = _scope(tmp_path)
    _patch_root(monkeypatch, client_root)
    runner = CliRunner()
    _reject_once(runner)
    original = research_report_submission.checked_component_preflight

    def supersede(**values):
        component = {
            "component_id": values["component_id"],
            "kind": values["kind"],
            "title": values["title"],
            "parent_id": None,
            "body": values["body"],
            "content": values["content"],
            "display_kind": values["display_kind"],
        }
        begin_submission(
            package_root=values["scope"].package_root,
            branch_id=values["scope"].branch_id,
            requested_sequence=1,
            logical_identity=component_identity(component),
            payload={"newer": "retry"},
        )
        return [], [{
            "component_id": "finding", "field": "body",
            "line": 1, "column": 1, "code": "forced",
            "message": "旧重试失败", "rule": "重试", "example": "retry",
        }]

    monkeypatch.setattr(
        research_report_submission, "checked_component_preflight", supersede,
    )
    stale = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "finding", "--kind", "chapter",
        "--title", "结论", "--body", "修正",
        "--submission-sequence", "1", "--json",
    ])
    monkeypatch.setattr(
        research_report_submission, "checked_component_preflight", original,
    )

    assert stale.exit_code == 1
    value = json.loads(stale.output)
    assert value["status"] == "blocked"
    assert value["submission_sequence"] == 1
    assert value["attempt"] == 3
    assert value["required_action"] == "correct_same_submission"


def test_asset_and_render_return_json_gate_while_pending(
    tmp_path, monkeypatch,
) -> None:
    client_root, _workspace_root = _scope(tmp_path)
    _patch_root(monkeypatch, client_root)
    runner = CliRunner()
    _reject_once(runner)
    asset = tmp_path / "asset.json"
    asset.write_text(json.dumps({
        "asset_ref": "asset:test", "kind": "file", "path": "x.csv",
        "label": "测试", "metadata": {},
    }), encoding="utf-8")

    blocked_asset = runner.invoke(report_cli, [
        "asset", *_args(), "--asset-file", str(asset), "--json",
    ])
    blocked_render = runner.invoke(report_cli, [
        "render", *_args(), "--json",
    ])

    for result in (blocked_asset, blocked_render):
        assert result.exit_code == 1
        value = json.loads(result.output)
        assert value["status"] == "blocked"
        assert value["submission_sequence"] == 1
        assert value["required_action"] == "correct_same_submission"
