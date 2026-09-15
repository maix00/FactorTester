from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tools.cli.commands import research_report_export
from tools.cli.commands.research_report import report as report_cli
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.authoring import (
    ensure_branch_report_chapter,
)
from tools.cli.release.research_reporting.workspace import (
    initialize_work_package,
)


def _scope(tmp_path: Path) -> Path:
    client_root = tmp_path / "client"
    workspace = tmp_path / "workspace"
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=workspace,
    )
    profile["research_records"] = [{
        "record_id": "wp",
        "title": "报告",
        "status": "pending",
        "scope": {},
        "factor_family_versions": [],
        "agent_id": "research-maxa",
        "created_at": 1.0,
        "updated_at": 1.0,
        "workspace_ref": "workspace:one",
        "run_ref": "",
        "graph_instance_ref": "work-package:wp",
        "graph_branch_ref": "report-branch:main",
        "checkpoint_ref": "",
        "evidence_refs": [],
        "timeline_refs": [],
        "artifacts": [],
        "provenance": {"kind": "owned_research"},
    }]
    LocalProfileStore(client_root).save(profile)
    initialize_work_package(
        workspace_root=workspace,
        work_package_id="wp",
        branch_id="main",
        workspace_id="one",
        title="报告",
        branch_ref="report-branch:main",
    )
    ensure_branch_report_chapter(
        workspace_root=workspace,
        work_package_id="wp",
        title="报告",
        node_id="factor_semantics",
        branch_id="main",
        branch_ref="report-branch:main",
    )
    return client_root


def _args(output: Path, output_format: str) -> list[str]:
    return [
        "export",
        "--profile", "maxa",
        "--work-package-id", "wp",
        "--branch-id", "main",
        "--format", output_format,
        "--output", str(output),
        "--json",
    ]


def test_markdown_export_is_cli_owned_and_refuses_implicit_overwrite(
    tmp_path: Path, monkeypatch,
) -> None:
    client_root = _scope(tmp_path)
    monkeypatch.setattr(
        research_report_export,
        "load_profile_root",
        lambda _path: client_root,
    )
    output = tmp_path / "研究报告.md"
    runner = CliRunner()

    exported = runner.invoke(report_cli, _args(output, "markdown"))

    assert exported.exit_code == 0, exported.output
    payload = json.loads(exported.output)
    assert payload["format"] == "markdown"
    assert payload["output"] == str(output)
    written = output.read_text(encoding="utf-8")
    assert "# 因子语义" in written
    # The native export writes the same branch/version front matter.
    assert "- 分支：main" in written
    assert "- 作者 profile：maxa" in written
    assert "- 导出时间：" in written
    assert "报告版本" in written
    assert not (
        tmp_path / "workspace/research/wp/branches/main/REPORT.md"
    ).exists()
    rejected = runner.invoke(report_cli, _args(output, "markdown"))
    assert rejected.exit_code != 0
    assert "--force" in rejected.output


def test_pdf_export_invokes_the_configured_native_renderer(
    tmp_path: Path, monkeypatch,
) -> None:
    client_root = _scope(tmp_path)
    monkeypatch.setattr(
        research_report_export,
        "load_profile_root",
        lambda _path: client_root,
    )
    renderer = tmp_path / "factortester-report-renderer"
    renderer.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "test \"$1\" = --input\n"
        "test \"$3\" = --output\n"
        "printf '%%PDF-native-test' > \"$4\"\n",
        encoding="utf-8",
    )
    renderer.chmod(0o755)
    monkeypatch.setenv("FACTORTESTER_REPORT_RENDERER", str(renderer))
    output = tmp_path / "研究报告.pdf"

    exported = CliRunner().invoke(report_cli, _args(output, "pdf"))

    assert exported.exit_code == 0, exported.output
    assert output.read_bytes().startswith(b"%PDF-native-test")


def test_export_requires_the_matching_filename_extension(
    tmp_path: Path, monkeypatch,
) -> None:
    client_root = _scope(tmp_path)
    monkeypatch.setattr(
        research_report_export,
        "load_profile_root",
        lambda _path: client_root,
    )

    result = CliRunner().invoke(
        report_cli, _args(tmp_path / "report.txt", "pdf"),
    )

    assert result.exit_code != 0
    assert ".pdf" in result.output

