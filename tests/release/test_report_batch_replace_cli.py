from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.commands import (
    research_report_authoring,
    research_report_inspection,
)
from tools.cli.commands.research_report import report as report_cli
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.references import (
    preflight as preflight_module,
)
from tools.cli.release.research_reporting.workspace import initialize_work_package


def _scope(tmp_path):
    client_root, workspace = tmp_path / "client", tmp_path / "workspace"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=workspace,
    )
    profile["research_records"] = [{
        "record_id": "wp", "title": "报告", "status": "pending",
        "scope": {}, "factor_family_versions": [],
        "agent_id": "research-maxa", "created_at": 1.0, "updated_at": 1.0,
        "workspace_ref": "workspace:one", "run_ref": "",
        "graph_instance_ref": "work-package:wp",
        "graph_branch_ref": "report-branch:main",
        "checkpoint_ref": "", "evidence_refs": [], "timeline_refs": [],
        "artifacts": [], "provenance": {"kind": "owned_research"},
    }]
    LocalProfileStore(client_root).save(profile)
    initialize_work_package(
        workspace_root=workspace, work_package_id="wp", branch_id="main",
        workspace_id="one", title="报告",
        branch_ref="report-branch:main",
    )
    return client_root


def _args() -> list[str]:
    return [
        "--profile", "maxa", "--work-package-id", "wp",
        "--branch-id", "main",
    ]


def _write(path, operation):
    path.write_text(json.dumps(
        {"operations": [operation]}, ensure_ascii=False,
    ), encoding="utf-8")


def test_cli_add_batch_replaces_existing_component(tmp_path, monkeypatch) -> None:
    client_root = _scope(tmp_path)
    for module in (research_report_authoring, research_report_inspection):
        monkeypatch.setattr(module, "load_profile_root", lambda _path: client_root)
    monkeypatch.setattr(
        preflight_module, "validate_declared_reference",
        lambda *, reference, scope, client=None,
        allow_historical_entry_requirement=False: {
            "kind": reference.kind, "target_ref": reference.target_ref,
            "label": reference.label, "data": {"job_id": "one"},
        },
    )
    runner = CliRunner()
    assert runner.invoke(
        report_cli, ["create", *_args(), "--json"],
    ).exit_code == 0
    operations = tmp_path / "operations.json"
    _write(operations, {
        "op": "add", "component_id": "chapter", "kind": "chapter",
        "title": "旧章节", "body": "旧正文", "content": None,
        "display_kind": "",
    })
    added = runner.invoke(report_cli, [
        "add-batch", *_args(), "--operations-file", str(operations), "--json",
    ])
    assert added.exit_code == 0, added.output
    _write(operations, {
        "op": "replace", "component_id": "chapter",
        "title": "新章节",
        "body": "[任务](factortester://job/job%3Aone)",
        "content": "新内容", "display_kind": "finding",
    })
    replaced = runner.invoke(report_cli, [
        "add-batch", *_args(), "--operations-file", str(operations), "--json",
    ])
    assert replaced.exit_code == 0, replaced.output
    assert json.loads(replaced.output)["generation"] == 2
    shown = runner.invoke(report_cli, ["show", *_args(), "--json"])
    payload = json.loads(shown.output)
    assert payload["components"][0]["title"] == "新章节"
    assert payload["components"][0]["content"] == "新内容"
    assert payload["bindings"][0]["target_ref"] == "job:one"
