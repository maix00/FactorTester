from __future__ import annotations

from pathlib import Path

import pytest

from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
)


def _add(
    package: Path, component_id: str, kind: str, parent_id: str | None,
) -> None:
    add_component(
        package_root=package, branch_id="main",
        component_id=component_id, kind=kind, title=component_id,
        parent_id=parent_id, body="", content=None, display_kind="",
    )


def _add_special(
    package: Path, component_id: str, parent_id: str,
    display_kind: str,
) -> None:
    add_component(
        package_root=package, branch_id="main",
        component_id=component_id, kind="special", title=component_id,
        parent_id=parent_id, body="", content=None,
        display_kind=display_kind,
    )


def test_legacy_subsection_is_a_nested_section(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    _add(package, "chapter", "chapter", None)
    _add(package, "section", "section", "chapter")
    _add(package, "nested-section", "section", "section")
    _add(package, "legacy-subsection", "subsection", "nested-section")
    _add(package, "entry", "entry", "legacy-subsection")

    with pytest.raises(ValueError, match="parent kind"):
        _add(package, "invalid-section", "section", "entry")


def test_report_special_sections_do_not_require_graph_continuations(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    _add(package, "chapter", "chapter", None)
    _add_special(package, "gap", "chapter", "research_gap")
    _add(package, "nested-section", "section", "gap")


def test_special_section_may_contain_deeper_report_sections(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    _add(package, "chapter", "chapter", None)
    _add_special(package, "gap", "chapter", "research_gap")
    _add(package, "section", "section", "gap")
    _add(package, "subsection", "subsection", "section")
