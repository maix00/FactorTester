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


def test_single_component_add_enforces_report_parent_kinds(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    _add(package, "chapter", "chapter", None)
    _add(package, "entry", "entry", "chapter")

    for component_id, kind, parent_id in [
        ("nested-section", "section", "entry"),
        ("direct-subsection", "subsection", "chapter"),
    ]:
        before = created["paths"]["head"].read_bytes()
        with pytest.raises(ValueError, match="parent kind"):
            _add(package, component_id, kind, parent_id)
        assert created["paths"]["head"].read_bytes() == before


def test_capability_special_may_contain_graph_continuation(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    _add(package, "chapter", "chapter", None)
    _add_special(package, "detour", "chapter", "capability_detour")
    _add_special(
        package, "upgrade", "detour", "graph_continuation",
    )


def test_special_section_may_contain_deeper_report_sections(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    _add(package, "chapter", "chapter", None)
    _add_special(package, "detour", "chapter", "capability_detour")
    _add(package, "section", "section", "detour")
    _add(package, "subsection", "subsection", "section")
