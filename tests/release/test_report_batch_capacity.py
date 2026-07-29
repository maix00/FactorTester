from __future__ import annotations

from pathlib import Path

import pytest

from tools.cli.release.research_reporting.authoring.tree_model import (
    apply_batch,
    initialize_tree,
)


def _chapter(index: int) -> dict[str, object]:
    return {
        "op": "add", "component_id": f"chapter-{index}",
        "kind": "chapter", "title": f"章节 {index}", "body": "",
        "content": None, "display_kind": "", "bindings": [],
    }


def test_atomic_report_batch_supports_bounded_historical_migration(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )

    saved = apply_batch(
        package_root=package, branch_id="main",
        operations=[_chapter(index) for index in range(129)],
    )

    assert saved["head"]["generation"] == 1
    assert len(saved["components"]) == 129


def test_atomic_report_batch_remains_bounded(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )

    with pytest.raises(ValueError, match="1 to 256"):
        apply_batch(
            package_root=package, branch_id="main",
            operations=[_chapter(index) for index in range(257)],
        )
