from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from cli_anything.factortester_research.factortester_research_cli import cli
from tools.cli.release.research_reporting.authoring import (
    ensure_branch_report_chapter,
)
from tools.cli.release.research_reporting.workspace import initialize_work_package


def test_profile_report_creation_exposes_branch_owned_node_anchor(
    tmp_path: Path,
) -> None:
    initialize_work_package(
        workspace_root=tmp_path,
        work_package_id="work-package-1",
        branch_id="branch-1",
        workspace_id="workspace-1",
        title="动量因子研究",
        branch_ref="graph-branch:work-package-1:branch-1",
    )
    result = ensure_branch_report_chapter(
        workspace_root=tmp_path,
        work_package_id="work-package-1",
        title="动量因子研究",
        node_id="hypothesis_preregistration",
        branch_id="branch-1",
        branch_ref="graph-branch:work-package-1:branch-1",
    )

    descriptor = result["descriptor"]
    assert descriptor["format"] == "document"
    assert len(descriptor["section_refs"]) == 1
    anchor = descriptor["section_refs"][0]
    assert anchor["kind"] == "report_section"
    assert anchor["target_ref"] == "node:hypothesis_preregistration"
    assert anchor["label"] == "假设登记"
    assert result["paths"]["document"].is_file()
    assert "/branches/branch-1/" in str(result["paths"]["document"])
    assert not (tmp_path / "research" / "work-package-1" / "REPORT.json").exists()


def test_harness_uses_the_production_scoped_report_surface() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["report", "add", "--help"])

    assert result.exit_code == 0, result.output
    assert "--profile" in result.output
    assert "--work-package-id" in result.output
    assert "--branch-id" in result.output
    assert "--file" not in result.output


def test_node_entry_is_idempotent_in_the_same_work_package_branch(
    tmp_path: Path,
) -> None:
    initialize_work_package(
        workspace_root=tmp_path,
        work_package_id="work-package-1",
        branch_id="branch-1",
        workspace_id="workspace-1",
        title="动量因子研究",
        branch_ref="graph-branch:work-package-1:branch-1",
    )
    first = ensure_branch_report_chapter(
        workspace_root=tmp_path,
        work_package_id="work-package-1",
        title="动量因子研究",
        node_id="factor_semantics",
        branch_id="branch-1",
        branch_ref="graph-branch:work-package-1:branch-1",
    )
    second = ensure_branch_report_chapter(
        workspace_root=tmp_path,
        work_package_id="work-package-1",
        title="动量因子研究",
        node_id="factor_semantics",
        branch_id="branch-1",
        branch_ref="graph-branch:work-package-1:branch-1",
    )

    assert first["chapter_sync"]["created_count"] == 1
    assert second["chapter_sync"]["created_count"] == 0
    saved = json.loads(
        first["paths"]["document"].read_text(encoding="utf-8")
    )
    assert [item["title"] for item in saved["components"]] == ["因子语义"]
