from __future__ import annotations

from tools.cli.release.research_reporting.authoring.tree_fork import (
    inherit_continuation_report_tree,
)
from tools.cli.release.research_reporting.authoring.checkpoint_publish import (
    publish_checkpoint_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
    load_snapshot,
)
from tools.cli.release.research_reporting.git import commit_work_package
from tests.release.test_entry_resolution_report_events import (
    _event_envelope,
)


def _special(package, branch, component_id, parent_id, episode):
    return add_component(
        package_root=package, branch_id=branch,
        component_id=component_id, kind="special", title=component_id,
        parent_id=parent_id, body="",
        content={"episode_ref": episode, "status": "pending"},
        display_kind="capability_detour",
        bindings=[{
            "binding_id": f"binding-{component_id}",
            "kind": "graph_reference", "target_ref": episode,
            "label": "能力绕行",
            "data": {"role": "capability_detour"},
        }],
        include_snapshot=False,
    )


def test_continuation_inherits_active_detour_once(tmp_path) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="source",
        report_id="report-source", title="研究报告",
    )
    add_component(
        package_root=package, branch_id="source",
        component_id="chapter", kind="chapter", title="假设登记",
        parent_id=None, body="", content=None, display_kind="",
        include_snapshot=False,
    )
    _special(package, "source", "detour", "chapter", "detour:active")

    first = inherit_continuation_report_tree(
        package_root=package, source_branch_id="source",
        target_branch_id="target", target_report_id="report-source",
    )
    add_component(
        package_root=package, branch_id="target",
        component_id="upgrade", kind="special", title="图升级",
        parent_id="detour", body="", content=None,
        display_kind="graph_continuation", include_snapshot=False,
    )
    repeated = inherit_continuation_report_tree(
        package_root=package, source_branch_id="source",
        target_branch_id="target", target_report_id="report-source",
    )

    snapshot = load_snapshot(package_root=package, branch_id="target")
    indexed = {
        item["component_id"]: item for item in snapshot["components"]
    }
    assert first["inherited"] is True
    assert repeated["inherited"] is False
    assert indexed["detour"]["parent_id"] == "chapter"
    assert indexed["upgrade"]["parent_id"] == "detour"
    assert indexed["detour"]["content"]["episode_ref"] == "detour:active"


def test_upgrade_special_uses_top_detour_without_chapter_or_episode_change(
    tmp_path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="target",
        report_id="report-target", title="研究报告",
    )
    add_component(
        package_root=package, branch_id="target",
        component_id="chapter", kind="chapter", title="假设登记",
        parent_id=None, body="", content=None, display_kind="",
        include_snapshot=False,
    )
    _special(package, "target", "detour", "chapter", "detour:active")
    before = load_snapshot(package_root=package, branch_id="target")
    episode_content = {
        item["component_id"]: item["content"]
        for item in before["components"]
        if item["display_kind"] == "capability_detour"
    }
    commit_work_package(package, message="Prepare inherited report")

    publish_checkpoint_snapshot(
        package_root=package, work_package_id="wp",
        branch_id="target",
        branch_ref="graph-branch:target:target",
        title="研究报告", node_id="capability_gap",
        report_parent_id="detour",
        snapshot={
            "assets": [],
            "sections": [{
                "section_id": "upgrade", "title": "研究图升级",
                "chapter_ref": "node:capability_gap",
                "section_role": "upgrade_reentry", "body": "",
                "links": [{
                    "link_id": "checkpoint", "kind": "checkpoint",
                    "target_ref": "trace:checkpoint-1",
                    "label": "升级检查点",
                }],
                "blocks": [{
                    "kind": "paragraph", "text": "保留能力绕行后升级研究图",
                    "link_ids": ["checkpoint"],
                }],
            }],
            "gaps": [],
        },
        entry_resolution_event=_event_envelope(),
        checkpoint_ref="trace:checkpoint-1",
    )

    saved = load_snapshot(package_root=package, branch_id="target")
    chapters = [item for item in saved["components"]
                if item["kind"] == "chapter"]
    upgrade = next(
        item for item in saved["components"]
        if item["display_kind"] == "graph_continuation"
    )
    assert [item["component_id"] for item in chapters] == ["chapter"]
    assert upgrade["parent_id"] == "detour"
    assert {
        item["component_id"]: item["content"]
        for item in saved["components"]
        if item["display_kind"] == "capability_detour"
    } == episode_content
    event_entries = [
        item for item in saved["components"]
        if item["parent_id"] == upgrade["component_id"]
        and item["kind"] == "entry"
        and item["component_id"].startswith("entry-resolution-")
    ]
    assert event_entries == []
    receipt = next(
        item for item in saved["bindings"]
        if item["kind"] == "checkpoint"
        and item["target_ref"] == "trace:checkpoint-1"
        and (item.get("data") or {}).get("role") == "checkpoint_receipt"
    )
    assert receipt["component_id"] == upgrade["component_id"]
