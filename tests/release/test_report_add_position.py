from __future__ import annotations

from pathlib import Path

import pytest

from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    apply_batch,
    initialize_tree,
    load_snapshot,
)


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    return package, created["paths"]["head"]


def _add(
    package: Path, component_id: str, kind: str, parent_id: str | None,
) -> None:
    add_component(
        package_root=package, branch_id="main",
        component_id=component_id, kind=kind,
        title=component_id if kind == "chapter" else "",
        parent_id=parent_id, body="", content=None, display_kind="",
    )


def _children(package: Path, parent_id: str) -> list[str]:
    snapshot = load_snapshot(package_root=package, branch_id="main")
    return [
        item["component_id"] for item in snapshot["components"]
        if item["parent_id"] == parent_id
    ]


def test_batch_add_can_insert_before_and_after_siblings(tmp_path: Path) -> None:
    package, _head = _tree(tmp_path)
    _add(package, "chapter", "chapter", None)
    _add(package, "a", "entry", "chapter")
    _add(package, "d", "entry", "chapter")

    apply_batch(
        package_root=package, branch_id="main", operations=[
            {
                "op": "add", "component_id": "b", "kind": "entry",
                "parent_id": "chapter", "title": "", "body": "",
                "before_component_id": "d",
            },
            {
                "op": "add", "component_id": "c", "kind": "entry",
                "parent_id": "chapter", "title": "", "body": "",
                "after_component_id": "b",
            },
        ],
    )

    assert _children(package, "chapter") == ["a", "b", "c", "d"]


@pytest.mark.parametrize(
    "position, message",
    [
        ({"before_component_id": "foreign"}, "same parent"),
        (
            {
                "before_component_id": "anchor",
                "after_component_id": "anchor",
            },
            "mutually exclusive",
        ),
    ],
)
def test_add_position_rejection_does_not_publish(
    tmp_path: Path, position: dict[str, str], message: str,
) -> None:
    package, head = _tree(tmp_path)
    _add(package, "chapter", "chapter", None)
    _add(package, "other", "chapter", None)
    _add(package, "anchor", "entry", "chapter")
    _add(package, "foreign", "entry", "other")
    before = head.read_bytes()

    with pytest.raises(ValueError, match=message):
        apply_batch(
            package_root=package, branch_id="main", operations=[{
                "op": "add", "component_id": "new", "kind": "entry",
                "parent_id": "chapter", "title": "", "body": "",
                **position,
            }],
        )

    assert head.read_bytes() == before
    assert "new" not in _children(package, "chapter")
