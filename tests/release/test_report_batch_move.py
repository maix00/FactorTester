from __future__ import annotations

from pathlib import Path

from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    apply_batch,
    initialize_tree,
)


def _add(
    package: Path, component_id: str, kind: str, parent_id: str | None,
    *, bindings: list[dict] | None = None,
) -> None:
    add_component(
        package_root=package, branch_id="main",
        component_id=component_id, kind=kind, title=component_id,
        parent_id=parent_id, body=f"body:{component_id}", content=None,
        display_kind="", bindings=bindings,
    )


def test_move_reparents_existing_subtree_without_recreating_it(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    _add(package, "chapter-a", "chapter", None)
    _add(package, "chapter-b", "chapter", None)
    _add(package, "section", "section", "chapter-a", bindings=[{
        "binding_id": "evidence-one", "kind": "evidence",
        "target_ref": "evidence:one", "label": "证据", "data": {},
    }])
    _add(package, "entry", "entry", "section")
    before = apply_batch(
        package_root=package, branch_id="main",
        operations=[{
            "op": "replace", "component_id": "entry", "title": "条目",
            "body": "正文", "content": None, "display_kind": "",
            "bindings": [],
        }],
    )
    section_before = next(
        item for item in before["components"]
        if item["component_id"] == "section"
    )

    saved = apply_batch(
        package_root=package, branch_id="main",
        operations=[{
            "op": "move", "component_id": "section",
            "parent_id": "chapter-b", "after_component_id": None,
        }],
    )

    section = next(
        item for item in saved["components"]
        if item["component_id"] == "section"
    )
    entry = next(
        item for item in saved["components"]
        if item["component_id"] == "entry"
    )
    assert section == {**section_before, "parent_id": "chapter-b"}
    assert entry["parent_id"] == "section"
    assert saved["bindings"][0]["component_id"] == "section"


def test_batch_can_add_parent_then_replace_and_move_same_component(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    _add(package, "old-chapter", "chapter", None)
    _add(package, "finding", "entry", "old-chapter")
    before = apply_batch(
        package_root=package, branch_id="main",
        operations=[{
            "op": "replace", "component_id": "finding", "title": "旧结论",
            "body": "旧正文", "content": None, "display_kind": "",
            "bindings": [],
        }],
    )

    saved = apply_batch(
        package_root=package, branch_id="main",
        operations=[
            {
                "op": "add", "component_id": "new-chapter",
                "kind": "chapter", "title": "新章节", "body": "",
                "content": None, "display_kind": "", "bindings": [],
            },
            {
                "op": "add", "component_id": "new-section",
                "kind": "section", "parent_id": "new-chapter",
                "title": "新小节", "body": "", "content": None,
                "display_kind": "", "bindings": [],
            },
            {
                "op": "replace", "component_id": "finding",
                "title": "新结论", "body": "新正文", "content": None,
                "display_kind": "finding", "bindings": [],
            },
            {
                "op": "move", "component_id": "finding",
                "parent_id": "new-section", "after_component_id": None,
            },
        ],
    )

    finding = next(
        item for item in saved["components"]
        if item["component_id"] == "finding"
    )
    assert saved["head"]["generation"] == before["head"]["generation"] + 1
    assert finding["parent_id"] == "new-section"
    assert (finding["title"], finding["body"], finding["display_kind"]) == (
        "新结论", "新正文", "finding",
    )
