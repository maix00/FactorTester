from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from tools.cli.commands import research_report_authoring
from tools.cli.commands import research_report_component
from tools.cli.commands import research_report_inspection
from tools.cli.commands.research_report import report as report_cli
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.workspace import initialize_work_package


def _scope(tmp_path: Path) -> tuple[Path, Path]:
    client_root, workspace_root = tmp_path / "client", tmp_path / "workspace"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=workspace_root,
    )
    profile["research_records"] = [{
        "record_id": "wp", "title": "报告", "status": "pending",
        "scope": {}, "factor_family_versions": [], "agent_id": "research-maxa",
        "created_at": 1.0, "updated_at": 1.0,
        "workspace_ref": "workspace:one", "run_ref": "",
        "graph_instance_ref": "work-package:wp",
        "graph_branch_ref": "report-branch:main",
        "checkpoint_ref": "", "evidence_refs": [], "timeline_refs": [],
        "artifacts": [], "provenance": {"kind": "owned_research"},
    }]
    LocalProfileStore(client_root).save(profile)
    initialize_work_package(
        workspace_root=workspace_root, work_package_id="wp", branch_id="main",
        workspace_id="one", title="报告",
        branch_ref="report-branch:main",
    )
    return client_root, workspace_root


def _args() -> list[str]:
    return [
        "--profile", "maxa", "--work-package-id", "wp",
        "--branch-id", "main",
    ]


def test_cli_rejects_then_publishes_only_corrected_same_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, workspace_root = _scope(tmp_path)
    for module in (
        research_report_authoring,
        research_report_component,
        research_report_inspection,
    ):
        monkeypatch.setattr(module, "load_profile_root", lambda _path: client_root)
    runner = CliRunner()
    assert runner.invoke(report_cli, ["create", *_args(), "--json"]).exit_code == 0

    rejected = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "finding", "--kind", "chapter",
        "--title", "结论", "--body", r"错误公式 \(", "--json",
    ])
    error = json.loads(rejected.output)
    assert rejected.exit_code == 1
    assert error["submission_sequence"] == 1
    assert error["diagnostics"][0]["code"] == "report.math.invalid"
    authoring = (
        workspace_root / "research" / "wp" / "branches" / "main" / "authoring"
    )
    assert json.loads((authoring / "HEAD.json").read_text())["generation"] == 0
    shown = runner.invoke(report_cli, ["show", *_args(), "--json"])
    assert shown.exit_code == 0
    shown_value = json.loads(shown.output)
    assert shown_value["pending_submission"]["submission_sequence"] == 1
    assert shown_value["pending_submission"]["attempt"] == 1
    assert shown_value["pending_submission"]["diagnostics"]
    validated = json.loads(
        runner.invoke(report_cli, ["validate", *_args(), "--json"]).output
    )
    assert validated["current_head_valid"] is True
    assert validated["writable"] is False
    assert validated["submission_status"] == "blocked"
    human = runner.invoke(report_cli, ["show", *_args()])
    assert "--submission-sequence 1" in human.output

    accepted = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "finding", "--kind", "chapter",
        "--title", "结论", "--body", r"正确公式 \(r_t\)",
        "--submission-sequence", "1", "--json",
    ])
    assert accepted.exit_code == 0, accepted.output
    result = json.loads(accepted.output)
    assert result["generation"] == result["submission_sequence"] == 1
    assert not (authoring / "pending-submission.json").exists()


def test_cli_allows_kind_and_parent_correction_for_same_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, _workspace_root = _scope(tmp_path)
    for module in (research_report_authoring, research_report_component):
        monkeypatch.setattr(module, "load_profile_root", lambda _path: client_root)
    runner = CliRunner()
    assert runner.invoke(report_cli, ["create", *_args(), "--json"]).exit_code == 0

    rejected = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "finding", "--kind", "entry",
        "--parent-id", "missing", "--title", "结论", "--json",
    ])
    assert json.loads(rejected.output)["submission_sequence"] == 1

    accepted = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "finding", "--kind", "chapter",
        "--title", "结论", "--submission-sequence", "1", "--json",
    ])
    assert accepted.exit_code == 0, accepted.output
    assert json.loads(accepted.output)["generation"] == 1


def test_human_rejection_prints_location_rule_and_retry_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, _workspace_root = _scope(tmp_path)
    for module in (research_report_authoring, research_report_component):
        monkeypatch.setattr(module, "load_profile_root", lambda _path: client_root)
    runner = CliRunner()
    assert runner.invoke(report_cli, ["create", *_args()]).exit_code == 0

    rejected = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "finding", "--kind", "chapter",
        "--title", "结论", "--body", r"错误公式 \(",
    ])
    assert rejected.exit_code == 1
    assert "报告提交 1" in rejected.output
    assert "被拦截" in rejected.output
    assert "finding.body 1:" in rejected.output
    assert "规则：" in rejected.output
    assert "示例：" in rejected.output
