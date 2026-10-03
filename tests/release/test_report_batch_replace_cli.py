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
from tools.cli.release.research_reporting.workspace import initialize_report_workspace


def _scope(tmp_path):
    client_root, workspace = tmp_path / "client", tmp_path / "workspace"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=workspace,
    )
    LocalProfileStore(client_root).save(profile)
    initialize_report_workspace(
        workspace_root=workspace, report_workspace_id="wp", branch_id="main",
        report_id="report-test",
        workspace_id="one", title="报告",
        branch_ref="report-branch:main",
    )
    return client_root


def _args() -> list[str]:
    return [
        "--profile", "maxa", "--report-workspace-id", "wp",
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


def test_cli_imports_workspace_png_into_exact_branch(tmp_path, monkeypatch):
    import base64
    from tools.cli.release.research_reporting.authoring import load_branch_authoring
    from tools.cli.release.research_reporting.public_research.projection import read_local_asset, asset_id_for

    client_root = _scope(tmp_path)
    monkeypatch.setattr(research_report_authoring, "load_profile_root", lambda _path: client_root)
    workspace = tmp_path / "workspace"
    source = workspace / "uploads" / "图片.png"
    source.parent.mkdir()
    raw = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    source.write_bytes(raw)
    runner = CliRunner()
    result = runner.invoke(report_cli, ["asset", *_args(), "--input", str(source), "--caption", "工作区图片", "--json"])
    assert result.exit_code == 0, result.output
    ref = json.loads(result.output)["asset_ref"]
    assert source.read_bytes() == raw
    package = workspace / "research" / "wp"
    snapshot = load_branch_authoring(package_root=package, branch_id="main")
    assert snapshot["head"]["assets"][0]["asset_ref"] == ref
    assert read_local_asset(snapshot, asset_id_for(ref))[0] == raw
    operations = tmp_path / "image-operations.json"
    operations.write_text(json.dumps({"operations": [
        {"op": "add", "component_id": "photos", "kind": "chapter", "title": "图片"},
        {"op": "add", "component_id": "photo", "kind": "image", "parent_id": "photos",
         "content": {"asset_ref": ref}},
    ]}), encoding="utf-8")
    added = runner.invoke(report_cli, ["add-batch", *_args(), "--operations-file", str(operations), "--json"])
    assert added.exit_code == 0, added.output
    snapshot = load_branch_authoring(package_root=package, branch_id="main")
    assert any(item.get("content") == {"asset_ref": ref} for item in snapshot["components"])
    source.unlink()
    assert read_local_asset(snapshot, asset_id_for(ref))[0] == raw
    initialize_report_workspace(workspace_root=workspace, report_workspace_id="wp", branch_id="other",
                            report_id="report-test",
                            workspace_id="one", title="其他分支", branch_ref="report-branch:other")
    other = load_branch_authoring(package_root=package, branch_id="other")
    assert read_local_asset(other, asset_id_for(ref)) is None
