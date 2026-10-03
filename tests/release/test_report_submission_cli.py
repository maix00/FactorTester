from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from tools.cli.commands import research_report_authoring
from tools.cli.commands import research_report_component
from tools.cli.commands import research_report_inspection
from tools.cli.commands.research_report import report as report_cli
from tools.cli.commands.research_report_content_structure import (
    validate_titled_chapter_content,
)
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.authoring.tree_model import load_snapshot
from tools.cli.release.research_reporting.workspace import initialize_report_workspace


def _scope(tmp_path: Path) -> tuple[Path, Path]:
    client_root, workspace_root = tmp_path / "client", tmp_path / "workspace"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=workspace_root,
    )
    LocalProfileStore(client_root).save(profile)
    initialize_report_workspace(
        workspace_root=workspace_root, report_workspace_id="wp", branch_id="main",
        report_id="report-wp", workspace_id="one", title="报告",
        branch_ref="report-branch:main",
    )
    return client_root, workspace_root


def _args() -> list[str]:
    return [
        "--profile", "maxa", "--report-workspace-id", "wp",
        "--branch-id", "main",
    ]


def test_cli_title_is_optional_only_for_content_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, workspace_root = _scope(tmp_path)
    for module in (research_report_authoring, research_report_component):
        monkeypatch.setattr(
            module, "load_profile_root", lambda _path: client_root,
        )
    runner = CliRunner()
    assert runner.invoke(
        report_cli, ["create", *_args(), "--json"],
    ).exit_code == 0
    chapter = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "chapter-one",
        "--kind", "chapter", "--title", "数据契约", "--json",
    ])
    assert chapter.exit_code == 0, chapter.output

    content = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "finding", "--kind", "entry",
        "--parent-id", "chapter-one", "--body", "数据覆盖已核验", "--json",
    ])
    assert content.exit_code == 0, content.output
    authoring = (
        workspace_root / "research" / "wp" / "branches" / "main" /
        "authoring"
    )
    assert json.loads((authoring / "HEAD.json").read_text())["generation"] == 2

    structure = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "section-one", "--kind", "section",
        "--parent-id", "chapter-one", "--json",
    ])
    assert structure.exit_code == 1
    assert "node.title" in structure.output


def test_cli_add_places_component_before_named_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, workspace_root = _scope(tmp_path)
    for module in (research_report_authoring, research_report_component):
        monkeypatch.setattr(
            module, "load_profile_root", lambda _path: client_root,
        )
    runner = CliRunner()
    assert runner.invoke(
        report_cli, ["create", *_args(), "--json"],
    ).exit_code == 0
    assert runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "chapter-one",
        "--kind", "chapter", "--title", "数据契约", "--json",
    ]).exit_code == 0
    for component_id in ("finding-a", "finding-c"):
        result = runner.invoke(report_cli, [
            "add", *_args(), "--component-id", component_id,
            "--kind", "entry", "--parent-id", "chapter-one",
            "--body", component_id, "--json",
        ])
        assert result.exit_code == 0, result.output

    inserted = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "finding-b",
        "--kind", "entry", "--parent-id", "chapter-one",
        "--body", "finding-b", "--before-component-id", "finding-c",
        "--json",
    ])

    assert inserted.exit_code == 0, inserted.output
    package = workspace_root / "research" / "wp"
    snapshot = load_snapshot(package_root=package, branch_id="main")
    assert [
        item["component_id"] for item in snapshot["components"]
        if item["parent_id"] == "chapter-one"
    ] == ["finding-a", "finding-b", "finding-c"]


def test_cli_rejects_titled_content_masquerading_as_chapter_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, _workspace_root = _scope(tmp_path)
    for module in (research_report_authoring, research_report_component):
        monkeypatch.setattr(
            module, "load_profile_root", lambda _path: client_root,
        )
    runner = CliRunner()
    assert runner.invoke(
        report_cli, ["create", *_args(), "--json"],
    ).exit_code == 0
    assert runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "chapter-one",
        "--kind", "chapter", "--title", "数据契约", "--json",
    ]).exit_code == 0

    rejected = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "pseudo-section",
        "--kind", "entry", "--parent-id", "chapter-one",
        "--title", "数据范围", "--body", "正文", "--json",
    ])

    assert rejected.exit_code == 1
    assert "content component cannot carry a section title" in rejected.output


@pytest.mark.parametrize("content_kind", ["list", "table"])
def test_titled_list_or_table_cannot_masquerade_as_chapter_section(
    content_kind: str,
) -> None:
    with pytest.raises(
        ValueError, match="content component cannot carry a section title",
    ):
        validate_titled_chapter_content({"components": [{
            "component_id": "chapter-one", "kind": "chapter",
        }]}, [{
            "op": "add", "component_id": "pseudo-section",
            "kind": content_kind, "parent_id": "chapter-one",
            "title": "数据范围",
        }])


def test_titled_content_is_rejected_inside_an_ordinary_section() -> None:
    with pytest.raises(
        ValueError, match="content component cannot carry a section title",
    ):
        validate_titled_chapter_content({"components": [{
            "component_id": "section-one", "kind": "section",
        }]}, [{
            "op": "add", "component_id": "pseudo-subsection",
            "kind": "entry", "parent_id": "section-one",
            "title": "数据范围",
        }])


def test_existing_content_cannot_be_replaced_with_a_title() -> None:
    with pytest.raises(
        ValueError, match="content component cannot carry a section title",
    ):
        validate_titled_chapter_content({"components": [{
            "component_id": "body-one", "kind": "entry",
        }]}, [{
            "op": "replace", "component_id": "body-one",
            "title": "数据范围", "body": "正文", "content": None,
            "display_kind": "", "bindings": [],
        }])


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
    assert rejected.exit_code == 1, (repr(rejected.exception), rejected.output)
    assert rejected.output, repr(rejected.exception)
    assert json.loads(rejected.output)["submission_sequence"] == 1

    accepted = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "finding", "--kind", "chapter",
        "--title", "结论", "--submission-sequence", "1", "--json",
    ])
    assert accepted.exit_code == 0, accepted.output
    assert json.loads(accepted.output)["generation"] == 1


def test_cli_requires_every_nonchapter_submission_to_name_its_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, _workspace_root = _scope(tmp_path)
    for module in (research_report_authoring, research_report_component):
        monkeypatch.setattr(
            module, "load_profile_root", lambda _path: client_root,
        )
    runner = CliRunner()
    assert runner.invoke(
        report_cli, ["create", *_args(), "--json"],
    ).exit_code == 0

    rejected = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "finding", "--kind", "entry",
        "--title", "结论", "--json",
    ])

    assert rejected.exit_code == 1
    payload = json.loads(rejected.output)
    diagnostic = payload["diagnostics"][0]
    assert payload["submission_sequence"] == 1
    assert diagnostic["field"] == "parent_id"
    assert diagnostic["code"] == "report.parent.required"
    assert diagnostic["rule"] == (
        "每次提交都要用 --parent-id 明确选择章节、特殊小节"
        "或其中的普通小节；不会继承上一条的位置"
    )


def test_cli_batch_requires_each_nonchapter_add_to_name_its_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, _workspace_root = _scope(tmp_path)
    for module in (research_report_authoring, research_report_component):
        monkeypatch.setattr(
            module, "load_profile_root", lambda _path: client_root,
        )
    runner = CliRunner()
    assert runner.invoke(
        report_cli, ["create", *_args(), "--json"],
    ).exit_code == 0
    operations = tmp_path / "operations.json"
    operations.write_text(json.dumps({"operations": [{
        "op": "add", "component_id": "finding", "kind": "entry",
        "title": "结论", "body": "", "content": None,
        "display_kind": "",
    }]}), encoding="utf-8")

    rejected = runner.invoke(report_cli, [
        "add-batch", *_args(), "--operations-file", str(operations),
        "--json",
    ])

    assert rejected.exit_code == 1
    payload = json.loads(rejected.output)
    assert payload["diagnostics"][0]["code"] == "report.parent.required"


def test_cli_enforces_nested_specials_and_inline_technical_identifiers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
    assert runner.invoke(
        report_cli, ["create", *_args(), "--json"],
    ).exit_code == 0
    chapter = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "chapter-one",
        "--kind", "chapter", "--title", "验证设计", "--json",
    ])
    assert chapter.exit_code == 0, chapter.output
    grill = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "grill-one",
        "--kind", "special", "--display-kind", "grill_resolution",
        "--parent-id", "chapter-one", "--title", "Grill 决议", "--json",
    ])
    assert grill.exit_code == 0, grill.output
    review = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "review-one",
        "--kind", "special", "--display-kind", "external_review",
        "--parent-id", "grill-one", "--title", "外部审计", "--json",
    ])
    assert review.exit_code == 0, review.output

    rejected = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "finding",
        "--kind", "entry", "--parent-id", "review-one",
        "--title", "审计发现", "--body", "调用 cs_rank 后复核",
        "--json",
    ])

    assert rejected.exit_code == 1
    payload = json.loads(rejected.output)
    assert payload["submission_sequence"] == 4
    assert payload["diagnostics"][0]["code"] == (
        "report.technical_identifier.unformatted"
    )
    accepted = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "finding",
        "--kind", "entry", "--parent-id", "review-one",
        "--body", "调用 `cs_rank` 后复核",
        "--submission-sequence", "4", "--json",
    ])
    assert accepted.exit_code == 0, accepted.output
    shown = json.loads(runner.invoke(
        report_cli, ["show", *_args(), "--json"],
    ).output)
    parents = {
        item["component_id"]: item["parent_id"]
        for item in shown["components"]
    }
    assert parents["grill-one"] == "chapter-one"
    assert parents["review-one"] == "grill-one"
    assert parents["finding"] == "review-one"


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
