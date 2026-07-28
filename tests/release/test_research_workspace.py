from __future__ import annotations

import json
from pathlib import Path
import subprocess

from tools.cli.release.research_reporting.workspace import (
    initialize_work_package,
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
    assert result["descriptor"]["format"] == "markdown"
    assert (package / "INDEX.json").exists()
    assert (package / "REPORT.md").exists()
    assert (package / "branches" / "branch-1" / "REPORT.md").exists()
    assert (package / "branches" / "branch-1" / "sections").is_dir()
    for name in ("assets", "artifacts", "migrations", "proposals", "protocol"):
        assert (package / name).is_dir()
    assert not (package / "protocol" / "chapters.json").exists()
    assert not (package / "branches" / "branch-1" / "JOURNAL.json").exists()
    assert not (package / "branches" / "branch-1" / "LOGICAL_JOURNAL.json").exists()

    index = json.loads((package / "INDEX.json").read_text(encoding="utf-8"))
    assert index["schema_version"] == 2
    assert index["branches"][0]["branch_id"] == "branch-1"
    assert index["sections"] == []
    assert (package / ".git").is_dir()
    assert subprocess.check_output(
        ["git", "-C", str(package), "status", "--short"], text=True,
    ) == ""

