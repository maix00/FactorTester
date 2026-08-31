from pathlib import Path

from tools.cli.release.research_reporting.authoring.tree_fork import (
    fork_report_tree,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
    load_snapshot,
)


def test_forked_report_changes_independently(tmp_path: Path) -> None:
    package = tmp_path / "research" / "package-a"
    initialize_tree(
        package_root=package,
        branch_id="source",
        report_id="report-source",
        title="研究报告",
    )
    add_component(
        package_root=package, branch_id="source",
        component_id="chapter-a", kind="chapter", title="假设登记",
        parent_id=None, body="", content=None, display_kind="",
    )
    fork_report_tree(
        package_root=package,
        source_branch_id="source",
        target_branch_id="target",
        target_report_id="report-source",
    )

    add_component(
        package_root=package, branch_id="target",
        component_id="fork-note", kind="entry", title="分支结论",
        parent_id="chapter-a", body="仅属于新分支",
        content=None, display_kind="",
    )
    source = load_snapshot(package_root=package, branch_id="source")
    target = load_snapshot(package_root=package, branch_id="target")

    assert [item["component_id"] for item in source["components"]] == [
        "chapter-a",
    ]
    assert [item["component_id"] for item in target["components"]] == [
        "chapter-a", "fork-note",
    ]
    assert target["head"]["report_id"] == source["head"]["report_id"]
