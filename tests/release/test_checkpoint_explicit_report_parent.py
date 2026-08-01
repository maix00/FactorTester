from __future__ import annotations

from tools.cli.release.research_reporting.authoring.checkpoint_publish import (
    publish_checkpoint_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    ensure_node_chapter,
    initialize_tree,
    load_snapshot,
)


def test_explicit_special_parent_never_creates_detour_node_chapter(tmp_path):
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    chapter = ensure_node_chapter(
        package_root=package, branch_id="main",
        node_id="hypothesis_preregistration", title="假设登记",
    )
    special_id = "special-capability-episode"
    add_component(
        package_root=package, branch_id="main", component_id=special_id,
        kind="special", title="能力修复过程",
        parent_id=chapter["component_id"], body="", content={},
        display_kind="capability_detour",
    )
    publish_checkpoint_snapshot(
        package_root=package, work_package_id="wp", branch_id="main",
        branch_ref="graph-branch:instance:main", title="研究报告",
        node_id="capability_gap", report_parent_id=special_id,
        snapshot={
            "assets": [], "gaps": [],
            "sections": [{
                "section_id": "repair-step", "title": "修复记录",
                "body": "已定位能力缺口",
                "links": [{
                    "link_id": "checkpoint", "kind": "checkpoint",
                    "target_ref": "trace:gap", "label": "报告检查点",
                }],
                "blocks": [{
                    "kind": "paragraph", "text": "等待修复",
                    "link_ids": ["checkpoint"],
                }],
            }],
        },
    )
    saved = load_snapshot(package_root=package, branch_id="main")
    chapters = [item for item in saved["components"]
                if item["kind"] == "chapter"]
    assert [item["title"] for item in chapters] == ["假设登记"]
    detour_children = [
        item for item in saved["components"]
        if item["parent_id"] == special_id
    ]
    assert {item["kind"] for item in detour_children} == {"entry"}
    assert {item["title"] for item in detour_children} >= {
        "修复记录", "",
    }
