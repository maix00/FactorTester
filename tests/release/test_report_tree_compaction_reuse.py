from pathlib import Path

from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    apply_batch,
    initialize_tree,
)


def test_noop_replacement_does_not_delete_reused_content_node(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    add_component(
        package_root=package, branch_id="main",
        component_id="chapter", kind="chapter", title="章节",
        parent_id=None, body="", content=None, display_kind="",
    )
    add_component(
        package_root=package, branch_id="main",
        component_id="entry", kind="entry", title="条目",
        parent_id="chapter", body="相同正文", content=None,
        display_kind="",
    )

    saved = apply_batch(
        package_root=package, branch_id="main", operations=[{
            "op": "replace", "component_id": "entry",
            "title": "条目", "body": "相同正文", "content": None,
            "display_kind": "", "bindings": [],
        }],
    )

    assert [item["component_id"] for item in saved["components"]] == [
        "chapter", "entry",
    ]
