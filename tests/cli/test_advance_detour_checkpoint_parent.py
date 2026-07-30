from __future__ import annotations

import json

from tests.release.report_tree_fixtures import carrier, narrative, profile
from tools.cli.commands.research_graph_local_report import (
    resolve_local_graph_report,
)
from tools.cli.commands.research_graph_navigation import (
    _publish_transition_report,
)
from tools.cli.commands.research_graph_report_policy import report_container
from tools.cli.commands.research_graph_report_sync import (
    synchronize_report_container,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    load_snapshot,
)
from tools.cli.release.research_reporting.workspace import initialize_work_package


def test_advance_checkpoint_uses_bound_legacy_detour_special(tmp_path):
    client_root = tmp_path / "client"
    profile(client_root)
    workspace = tmp_path / "client" / "profile-root"
    initialize_work_package(
        workspace_root=workspace, work_package_id="sgccs-review",
        branch_id="branch-sgccs", workspace_id="workspace-maxa",
        title="SgCCS review",
        branch_ref="graph-branch:sgccs-review:branch-sgccs",
    )
    scope = resolve_local_graph_report(
        client_root=client_root, profile_id="maxa",
        agent_id="research-maxa", instance_id="sgccs-review",
        branch_id="branch-sgccs",
    )
    chapter = synchronize_report_container(scope, container=report_container({
        "current_node": "hypothesis_preregistration",
        "report_container": {
            "kind": "chapter",
            "anchor_node": "hypothesis_preregistration",
        },
    }))
    legacy_id = "profile-screen-alias-capability-resolution"
    add_component(
        package_root=scope.package_root, branch_id=scope.branch_id,
        component_id=legacy_id, kind="special", title="既有能力修复",
        parent_id=chapter["component_id"], body="", content={},
        display_kind="capability_resolution", bindings=[{
            "binding_id": "legacy-episode", "kind": "graph_reference",
            "target_ref": "capability-detour:origin", "label": "能力修复",
            "data": {"role": "capability_detour"},
        }],
    )
    add_component(
        package_root=scope.package_root, branch_id=scope.branch_id,
        component_id="legacy-child", kind="entry", title="既有记录",
        parent_id=legacy_id, body="不得丢失", content=None, display_kind="",
    )
    outer = {
        "episode_id": "capability-detour:origin",
        "resume_node": "hypothesis_preregistration",
        "origin_trace_id": "origin",
        "report_container": {
            "kind": "special",
            "anchor_node": "hypothesis_preregistration",
            "episode_ref": "capability-detour:origin",
        },
    }
    special = synchronize_report_container(scope, container=report_container({
        "current_node": "capability_gap",
        "report_container": outer["report_container"],
        "capability_detour": {
            "schema_version": 1, "episode_id": "capability-detour:origin",
            "status": "retained",
            "resume_node": "hypothesis_preregistration",
            "origin_trace_id": "origin",
            "latest_trace_id": "checkpoint-1",
            "report_container": outer["report_container"],
        },
    }))
    value = carrier()
    value["current_node"] = "capability_gap"
    value["latest_transition"]["to_node"] = "capability_gap"
    narrative_file = tmp_path / "narrative.json"
    narrative_file.write_text(
        json.dumps(narrative(value), ensure_ascii=False), encoding="utf-8",
    )
    result = _publish_transition_report(
        branch={"report_checkpoint": value}, client_root=client_root,
        profile_id="maxa", agent_id="research-maxa",
        instance_id="sgccs-review", branch_id="branch-sgccs",
        narrative_file=narrative_file, chapter_sync=special,
    )
    assert result["status"] == "published"
    saved = load_snapshot(
        package_root=scope.package_root, branch_id=scope.branch_id,
    )
    assert [item["title"] for item in saved["components"]
            if item["kind"] == "chapter"] == ["假设预注册"]
    assert any(item["component_id"] == "legacy-child"
               and item["parent_id"] == legacy_id
               for item in saved["components"])
    assert any(item["parent_id"] == legacy_id
               and item["component_id"] != "legacy-child"
               for item in saved["components"])
