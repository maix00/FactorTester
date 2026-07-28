"""Rich-text report authoring acceptance seams."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click import ClickException
from click.testing import CliRunner

from tools.cli.commands import research_report_component
from tools.cli.commands.research_report import report
from tools.cli.commands.research_report_common import rich_body
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.authoring.tree_rich_text import (
    validate_rich_text,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    apply_batch,
    initialize_tree,
)
from tools.cli.release.research_reporting.workspace import initialize_work_package


def test_rich_body_accepts_portable_markdown(tmp_path: Path) -> None:
    source = tmp_path / "finding.md"
    source.write_text(
        "结论含 `SgCPS` 与 \\(IC_t\\)。\n\n"
        "```python\nscore = close.pct_change()\n```\n\n"
        "| 指标 | 值 |\n| --- | ---: |\n| IC | 0.03 |\n\n"
        "$$\nIR = \\frac{\\mu}{\\sigma}\n$$\n",
        encoding="utf-8",
    )

    body = rich_body(body=None, body_file=source)
    assert "score" in body
    assert validate_rich_text(body, field="node.body") == body


@pytest.mark.parametrize("body", [
    '{"columns":["指标"],"rows":[["IC"]]}',
    "```python\nunclosed = True",
    "| 指标 | 值 |\n| --- | --- |\n| IC | 0.03 | extra |",
    "$$\nIR = mu / sigma",
])
def test_report_tree_rejects_invalid_rich_body_before_writing(
    tmp_path: Path, body: str,
) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )

    with pytest.raises(ValueError):
        add_component(
            package_root=package, branch_id="main", component_id="chapter",
            kind="chapter", title="发现", parent_id=None, body=body,
            content=None, display_kind="",
        )

    assert created["head"]["generation"] == 0
    assert not (created["paths"]["nodes"] / "chapter").exists()


def test_report_batch_rejects_invalid_rich_body_before_writing(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )

    with pytest.raises(ValueError, match="JSON payload, not rich text"):
        apply_batch(
            package_root=package, branch_id="main", operations=[{
                "op": "add", "component_id": "chapter", "kind": "chapter",
                "title": "发现", "parent_id": None,
                "body": '{"columns":["指标"],"rows":[["IC"]]}',
                "content": None, "display_kind": "", "bindings": [],
            }],
        )

    assert created["head"]["generation"] == 0
    assert not (created["paths"]["nodes"] / "chapter").exists()


def test_report_tree_rejects_oversized_markdown_table() -> None:
    body = "| A | B |\n| --- | --- |\n" + "| 1 | 2 |\n" * 201

    with pytest.raises(ValueError, match="inline Markdown table limit"):
        validate_rich_text(body, field="node.body")


def test_rich_body_accepts_table_formulas_and_code_with_vertical_bars() -> None:
    body = (
        "| 指标 | 定义 |\n"
        "| --- | --- |\n"
        "| 范数 | \\(\\lVert r_t \\mid r_{t-1}\\rVert\\) |\n"
        "| 掩码 | `left | right` |\n"
    )

    assert validate_rich_text(body, field="node.body") == body


def test_report_add_reads_rich_body_file_and_reports_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root = tmp_path / "client"
    profile_root = tmp_path / "profile"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=profile_root,
    )
    profile["research_records"] = [{
        "record_id": "wp", "title": "研究报告", "status": "pending",
        "scope": {"factor_families": []}, "factor_family_versions": [],
        "agent_id": "research-maxa", "created_at": 1.0, "updated_at": 1.0,
        "workspace_ref": "workspace:ws", "run_ref": "",
        "graph_instance_ref": "work-package:wp",
        "graph_branch_ref": "graph-branch:ws:main", "checkpoint_ref": "",
        "evidence_refs": [], "timeline_refs": [], "artifacts": [],
        "provenance": {"kind": "owned_research"},
    }]
    LocalProfileStore(client_root).save(profile)
    initialize_work_package(
        workspace_root=profile_root, work_package_id="wp", branch_id="main",
        workspace_id="ws", title="研究报告", branch_ref="graph:main",
    )
    monkeypatch.setattr(
        research_report_component, "load_profile_root", lambda _path: client_root,
    )
    source = tmp_path / "finding.md"
    source.write_text("研究结论含 `SgCPS`。", encoding="utf-8")

    result = CliRunner().invoke(report, [
        "add", "--profile", "maxa", "--work-package-id", "wp",
        "--branch-id", "main", "--component-id", "chapter", "--kind",
        "chapter", "--title", "发现", "--body-file", str(source), "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["body_format"] == "restricted_markdown"


def test_report_add_rejects_inline_and_file_body_together(tmp_path: Path) -> None:
    source = tmp_path / "finding.md"
    source.write_text("正文", encoding="utf-8")

    with pytest.raises(ClickException, match="mutually exclusive"):
        rich_body(body="正文", body_file=source)
