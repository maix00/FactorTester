from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from tests.release.test_report_submission_cli import _args, _scope
from tools.cli.commands import (
    research_report_authoring,
    research_report_component,
    research_report_inspection,
    research_report_submission_finalize,
)
from tools.cli.commands.research_report import report as report_cli
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.research_reporting.authoring import (
    ensure_branch_report_chapter,
)
from tools.cli.release.research_reporting.authoring.tree_schema import digest


@pytest.mark.parametrize("command_kind", ["add", "add-batch"])
def test_published_retry_rebuilds_descriptor_from_current_head(
    tmp_path, monkeypatch: pytest.MonkeyPatch, command_kind: str,
) -> None:
    client_root, workspace_root = _scope(tmp_path)
    for module in (
        research_report_authoring,
        research_report_component,
        research_report_inspection,
    ):
        monkeypatch.setattr(
            module, "load_profile_root", lambda _path: client_root,
        )
    ensure_branch_report_chapter(
        workspace_root=workspace_root, work_package_id="wp", title="报告",
        node_id="data_contract", branch_id="main",
        branch_ref="graph-branch:instance:main",
    )
    original = research_report_submission_finalize.persist_descriptor
    monkeypatch.setattr(
        research_report_submission_finalize,
        "persist_descriptor",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("descriptor failed")
        ),
    )
    runner = CliRunner()
    if command_kind == "add":
        command = [
            "add", *_args(), "--component-id", "finding", "--kind", "section",
            "--parent-id", "chapter-e50bf914c6bbbd9b",
            "--title", "发现", "--json",
        ]
    else:
        operations = tmp_path / "operations.json"
        operations.write_text(json.dumps({"operations": [{
            "op": "add", "component_id": "finding", "kind": "section",
            "parent_id": "chapter-e50bf914c6bbbd9b", "title": "发现",
            "body": "", "content": None, "display_kind": "",
        }]}), encoding="utf-8")
        command = [
            "add-batch", *_args(), "--operations-file", str(operations),
            "--json",
        ]
    failed = runner.invoke(report_cli, command)
    assert failed.exit_code == 1, failed.output
    sequence = json.loads(failed.output)["submission_sequence"]

    monkeypatch.setattr(
        research_report_submission_finalize, "persist_descriptor", original,
    )
    retried = runner.invoke(
        report_cli, [*command[:-1], "--submission-sequence", str(sequence), "--json"],
    )
    assert retried.exit_code == 0, retried.output
    package = workspace_root / "research" / "wp"
    head = json.loads((
        package / "branches" / "main" / "authoring" / "HEAD.json"
    ).read_text())
    record = LocalProfileStore(client_root).load("maxa")["research_records"][0]
    descriptor = next(
        item for item in record["artifacts"] if item["format"] == "report_tree"
    )
    assert descriptor["content_hash"] == digest(head)
    assert descriptor["section_refs"] == [{
        "link_id": "chapter-node-e50bf914c6bbbd9b",
        "kind": "report_section",
        "target_ref": "node:data_contract",
        "section_ref": "chapter-e50bf914c6bbbd9b",
        "label": "数据契约",
    }]
