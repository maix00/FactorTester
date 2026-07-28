from __future__ import annotations

from pathlib import Path
import subprocess

from tools.cli.release.research_reporting.workspace import (
    initialize_work_package,
)
from tools.cli.release.research_reporting.package_layout import (
    ensure_branch_report_tree,
)


def test_initialize_matches_work_package_skeleton(tmp_path: Path) -> None:
    result = initialize_work_package(
        workspace_root=tmp_path,
        work_package_id="wp-1",
        branch_id="branch-1",
        workspace_id="workspace-1",
        title="研究工作包",
        branch_ref="graph-branch:instance-1:branch-1",
    )
    package = tmp_path / "research" / "wp-1"
    assert result["descriptor"]["format"] == "report_tree"
    assert (package / "branches" / "branch-1" / "authoring" / "HEAD.json").exists()
    assert (package / "branches" / "branch-1" / "REPORT.md").exists()
    for name in ("assets", "artifacts", "migrations", "proposals", "protocol"):
        assert (package / name).is_dir()
    assert not (package / "protocol" / "chapters.json").exists()
    assert not (package / "branches" / "branch-1" / "JOURNAL.json").exists()
    assert not (package / "branches" / "branch-1" / "LOGICAL_JOURNAL.json").exists()

    assert not (package / "INDEX.json").exists()
    assert not (package / "REPORT.md").exists()
    assert (package / ".git").is_dir()
    assert subprocess.check_output(
        ["git", "-C", str(package), "status", "--short"], text=True,
    ) == ""


def test_empty_materialized_branch_has_no_journal_until_checkpoint(
    tmp_path: Path,
) -> None:
    branch_root = ensure_branch_report_tree(tmp_path / "package", "fork-a")

    assert not (branch_root / "sections").exists()
    assert not (branch_root / "REPORT.md").exists()
    assert not (branch_root / "JOURNAL.json").exists()
