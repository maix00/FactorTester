from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.commands.research_report import report as report_cli
from tools.cli.commands import research_report_authoring
from tools.cli.commands import research_report_component
from tools.cli.commands import research_report_inspection
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.authoring.inline_links import (
    typed_markdown_link,
)
from tools.cli.release.research_reporting.references import preflight as preflight_module
from tools.cli.release.research_reporting.workspace import initialize_report_workspace


def _scoped_report(tmp_path):
    client_root = tmp_path / "client-root"
    workspace_root = tmp_path / "workspace-root"
    store = LocalProfileStore(client_root)
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=workspace_root,
    )
    store.save(profile)
    initialize_report_workspace(
        workspace_root=workspace_root,
        report_workspace_id="package-1",
        report_id="report-1",
        branch_id="branch-1",
        workspace_id="workspace-1",
        title="CLI 报告",
        branch_ref="report-branch:branch-1",
    )
    return client_root, workspace_root


def _scope_args() -> list[str]:
    return [
        "--profile", "maxa", "--report-workspace-id", "package-1",
        "--branch-id", "branch-1",
    ]


def test_report_cli_add_batch_commits_content_and_bindings(tmp_path, monkeypatch) -> None:
    client_root, workspace_root = _scoped_report(tmp_path)
    monkeypatch.setattr(
        research_report_authoring, "load_profile_root", lambda path: client_root,
    )
    monkeypatch.setattr(
        research_report_inspection, "load_profile_root", lambda path: client_root,
    )
    monkeypatch.setattr(
        research_report_component, "load_profile_root", lambda path: client_root,
    )
    monkeypatch.setattr(
        preflight_module,
        "validate_declared_reference",
        lambda *, reference, scope, client=None: {
            "kind": reference.kind,
            "target_ref": reference.target_ref,
            "label": reference.label,
            "data": {"job_id": "1"},
        },
    )
    runner = CliRunner()
    created = runner.invoke(report_cli, [
        "create", *_scope_args(), "--json",
    ])
    assert created.exit_code == 0, created.output
    operations = tmp_path / "operations.json"
    operations.write_text(json.dumps({"operations": [{
        "op": "add", "component_id": "findings", "kind": "chapter",
        "title": "Findings", "body": "", "content": None,
        "display_kind": "", "bindings": [{
            "binding_id": "job-1", "kind": "job", "target_ref": "job:1",
            "label": "", "data": {},
        }],
    }]}), encoding="utf-8")
    rejected = runner.invoke(report_cli, [
        "add-batch", *_scope_args(), "--operations-file", str(operations),
        "--json",
    ])
    assert rejected.exit_code == 1
    assert json.loads(rejected.output)["submission_sequence"] == 1
    operations.write_text(json.dumps({"operations": [{
        "op": "add", "component_id": "findings", "kind": "chapter",
        "title": "Findings",
        "body": typed_markdown_link(
            kind="job", target_ref="job:1", label="回测任务",
        ),
        "content": None, "display_kind": "",
    }]}), encoding="utf-8")
    added = runner.invoke(report_cli, [
        "add-batch", *_scope_args(), "--operations-file", str(operations),
        "--submission-sequence", "1", "--json",
    ])
    assert added.exit_code == 0, added.output
    assert json.loads(added.output)["generation"] == 1
    checked = runner.invoke(report_cli, ["validate", *_scope_args(), "--json"])
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.output)["bindings"] == 1
    head = (
        workspace_root / "research" / "package-1" / "branches" / "branch-1"
        / "authoring" / "HEAD.json"
    )
    assert json.loads(head.read_text(encoding="utf-8"))["generation"] == 1
    shown = runner.invoke(report_cli, ["show", *_scope_args(), "--json"])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["bindings"][0]["target_ref"] == "job:1"


def test_report_cli_authors_math_and_result_components(tmp_path, monkeypatch) -> None:
    client_root, workspace_root = _scoped_report(tmp_path)
    monkeypatch.setattr(
        research_report_authoring, "load_profile_root", lambda path: client_root,
    )
    monkeypatch.setattr(
        research_report_inspection, "load_profile_root", lambda path: client_root,
    )
    monkeypatch.setattr(
        research_report_component, "load_profile_root", lambda path: client_root,
    )
    runner = CliRunner()
    result_content = tmp_path / "result.json"
    code_file = tmp_path / "factor.py"
    result_content.write_text(json.dumps({"sharpe": 1.25}), encoding="utf-8")
    code_file.write_text("def signal(price):\n    return price\n", encoding="utf-8")
    assert runner.invoke(report_cli, [
        "create", *_scope_args(), "--json",
    ]).exit_code == 0
    chapter = runner.invoke(report_cli, [
        "add", *_scope_args(), "--component-id", "findings", "--kind", "chapter",
        "--title", "Findings", "--json",
    ])
    assert chapter.exit_code == 0, chapter.output
    added_math = runner.invoke(report_cli, [
        "add", *_scope_args(), "--component-id", "equation", "--kind", "math",
        "--latex", r"s_t = z_t / \sigma_t",
        "--fallback", "normalized signal", "--parent-id", "findings", "--json",
    ])
    assert added_math.exit_code == 0, added_math.output
    added_code = runner.invoke(report_cli, [
        "add", *_scope_args(), "--component-id", "source", "--kind", "code",
        "--language", "python",
        "--code-file", str(code_file), "--parent-id", "findings", "--json",
    ])
    assert added_code.exit_code == 0, added_code.output
    added_list = runner.invoke(report_cli, [
        "add", *_scope_args(), "--component-id", "constraints", "--kind", "list",
        "--item", "Keep 2026 sealed",
        "--item", "Record every window", "--parent-id", "findings", "--json",
    ])
    assert added_list.exit_code == 0, added_list.output
    added_result = runner.invoke(report_cli, [
        "add", *_scope_args(), "--component-id", "summary", "--kind", "result",
        "--content-file", str(result_content),
        "--parent-id", "findings", "--json",
    ])
    assert added_result.exit_code == 0, added_result.output
    rendered = runner.invoke(report_cli, [
        "render", *_scope_args(), "--json",
    ])
    assert rendered.exit_code == 0, rendered.output
    branch_root = (
        workspace_root / "research" / "package-1" / "branches" / "branch-1"
    )
    markdown = (branch_root / "REPORT.md").read_text(encoding="utf-8")
    assert "$$\ns_t = z_t / \\sigma_t\n$$" in markdown
    assert "```python\ndef signal(price):" in markdown
    assert "- Keep 2026 sealed\n- Record every window" in markdown
    assert '"sharpe": 1.25' in markdown
    assert (branch_root / "authoring" / "HEAD.json").is_file()
    assert not (branch_root / "authoring" / "REPORT.md").exists()
    assert not (workspace_root / "research" / "package-1" / "INDEX.json").exists()
