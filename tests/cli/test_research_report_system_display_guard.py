from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from tools.cli.commands import (
    research_report_authoring,
    research_report_component,
    research_report_component_write,
    research_report_graph_guard,
)
from tools.cli.commands.research_report import report
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    ensure_node_chapter,
    load_snapshot,
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
        "agent_id": "research-maxa", "created_at": 1, "updated_at": 1,
        "workspace_ref": "workspace:one", "run_ref": "",
        "graph_instance_ref": "work-package:wp",
        "graph_branch_ref": "graph-branch:instance:main",
        "checkpoint_ref": "", "evidence_refs": [], "timeline_refs": [],
        "artifacts": [], "provenance": {"kind": "owned_research"},
    }]
    LocalProfileStore(client_root).save(profile)
    initialized = initialize_work_package(
        workspace_root=workspace, work_package_id="wp", branch_id="main",
        workspace_id="one", title="报告",
        branch_ref="graph-branch:instance:main",
    )
    chapter = ensure_node_chapter(
        package_root=initialized["package_root"], branch_id="main",
        node_id="hypothesis_preregistration", title="假设登记",
    )
    return client_root, initialized["package_root"], chapter["component_id"]


def _patch(monkeypatch, client_root):
    for module in (research_report_authoring, research_report_component):
        monkeypatch.setattr(
            module, "load_profile_root", lambda _path: client_root,
        )
    monkeypatch.setattr(
        research_report_graph_guard, "fetch_graph_node_packet",
        lambda _scope: {
            "current_node": "hypothesis_preregistration",
            "report_container": {
                "kind": "chapter",
                "anchor_node": "hypothesis_preregistration",
            },
        },
    )


def _args():
    return [
        "--profile", "maxa", "--work-package-id", "wp",
        "--branch-id", "main",
    ]


@pytest.mark.parametrize(
    "display_kind", [
        "capability_detour",
        "graph_continuation",
        "obligation_changes",
        "research_gap",
        "test_result",
    ],
)
def test_cli_add_rejects_system_display_kind_as_json(
    tmp_path, monkeypatch, display_kind,
):
    client_root, _package, chapter_id = _scope(tmp_path)
    _patch(monkeypatch, client_root)
    result = CliRunner().invoke(report, [
        "add", *_args(), "--component-id", "forged", "--kind", "special",
        "--title", "伪造系统容器", "--parent-id", chapter_id,
        "--display-kind", display_kind, "--json",
    ])

    assert result.exit_code == 1
    value = json.loads(result.output)
    assert value["status"] == "rejected"
    assert value["submission_sequence"] == 2
    assert "system-owned" in value["diagnostics"][0]["message"]


def test_cli_batch_replace_rejects_system_display_kind_as_json(
    tmp_path, monkeypatch,
):
    client_root, package, chapter_id = _scope(tmp_path)
    _patch(monkeypatch, client_root)
    add_component(
        package_root=package, branch_id="main",
        component_id="finding", kind="entry", title="发现",
        parent_id=chapter_id, body="正文", content=None, display_kind="",
    )
    operations = tmp_path / "operations.json"
    operations.write_text(json.dumps({"operations": [{
        "op": "replace", "component_id": "finding", "title": "发现",
        "body": "正文", "content": None,
        "display_kind": "graph_continuation",
    }]}), encoding="utf-8")

    result = CliRunner().invoke(report, [
        "add-batch", *_args(), "--operations-file", str(operations), "--json",
    ])

    assert result.exit_code == 1
    value = json.loads(result.output)
    assert value["status"] == "rejected"
    assert value["submission_sequence"] == 3
    assert "system-owned" in value["diagnostics"][0]["message"]


def test_hidden_owner_authorization_creates_one_unbound_manual_chapter(
    tmp_path, monkeypatch,
):
    client_root, package, _chapter_id = _scope(tmp_path)
    _patch(monkeypatch, client_root)
    monkeypatch.setattr(
        research_report_component_write,
        "_owner_chapter_authorized",
        lambda value: value == 17,
    )
    runner = CliRunner()

    chapter = runner.invoke(report, [
        "add", *_args(), "--component-id", "owner-notes",
        "--kind", "chapter", "--title", "人工研究章节",
        "--owner-chapter-authorization", "17", "--json",
    ])
    assert chapter.exit_code == 0, chapter.output
    finding = runner.invoke(report, [
        "add", *_args(), "--component-id", "owner-finding",
        "--kind", "entry", "--parent-id", "owner-notes",
        "--body", "人工授权研究记录",
        "--owner-chapter-authorization", "17", "--json",
    ])
    assert finding.exit_code == 0, finding.output

    snapshot = load_snapshot(package_root=package, branch_id="main")
    components = {
        item["component_id"]: item for item in snapshot["components"]
    }
    assert components["owner-notes"]["parent_id"] is None
    assert components["owner-finding"]["parent_id"] == "owner-notes"
    assert not any(
        binding["component_id"] == "owner-notes"
        and binding["kind"] == "graph_reference"
        for binding in snapshot["bindings"]
    )


def test_wrong_owner_authorization_does_not_disclose_expected_value(
    tmp_path, monkeypatch,
):
    client_root, _package, _chapter_id = _scope(tmp_path)
    _patch(monkeypatch, client_root)

    result = CliRunner().invoke(report, [
        "add", *_args(), "--component-id", "owner-notes",
        "--kind", "chapter", "--title", "人工研究章节",
        "--owner-chapter-authorization", "1", "--json",
    ])

    assert result.exit_code == 1
    assert "system-owned" in result.output
    assert "owner-chapter-authorization" not in result.output
