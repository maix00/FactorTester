from __future__ import annotations

from tests.cli.test_research_graph_continuation_parent import _profile
from tools.cli.commands.research_graph_continuation_parent import (
    prepare_continuation_report_parent,
)
from tools.cli.release.research_reporting.authoring.checkpoint_publish import (
    publish_checkpoint_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    ensure_node_chapter,
    load_snapshot,
)
from tools.cli.release.research_reporting.workspace import initialize_work_package


EPISODE = "capability-detour:origin"


class _Client:
    def get_research_graph_node_info(self, _instance, _branch):
        frame = {
            "episode_id": EPISODE,
            "resume_node": "hypothesis_preregistration",
            "origin_trace_id": "origin",
            "report_container": {
                "kind": "special",
                "anchor_node": "hypothesis_preregistration",
                "episode_ref": EPISODE,
            },
        }
        return {
            "graph": "factor-research@v10",
            "node": {"node_id": "capability_gap"},
            "current_node": "capability_gap",
            "context_ref": "sha256:" + "1" * 64,
            "checkpoint_ref": "trace:gap-trace",
            "current_obligations": [],
            "entry_requirements": [],
            "report_container": frame["report_container"],
            "capability_detour": {
                "schema_version": 1, "status": "pending",
                "latest_trace_id": "gap-trace", **frame,
            },
        }


def test_continuation_upgrade_stays_inside_one_legacy_detour(tmp_path):
    client_root, workspace = tmp_path / "client", tmp_path / "workspace"
    _profile(client_root, workspace)
    initialized = initialize_work_package(
        workspace_root=workspace, work_package_id="wp",
        branch_id="source", workspace_id="one", title="研究",
        branch_ref="graph-branch:source:source",
    )
    chapter = ensure_node_chapter(
        package_root=initialized["package_root"], branch_id="source",
        node_id="hypothesis_preregistration", title="假设登记",
    )
    legacy_id = "profile-screen-alias-capability-resolution"
    add_component(
        package_root=initialized["package_root"], branch_id="source",
        component_id=legacy_id, kind="special", title="既有能力绕行",
        parent_id=chapter["component_id"], body="保留既有语义",
        content={"legacy": True}, display_kind="capability_resolution",
        bindings=[{
            "binding_id": "legacy-episode", "kind": "graph_reference",
            "target_ref": EPISODE, "label": "能力绕行",
            "data": {"role": "capability_detour"},
        }],
    )
    add_component(
        package_root=initialized["package_root"], branch_id="source",
        component_id="legacy-entry", kind="entry", title="既有记录",
        parent_id=legacy_id, body="不得丢失", content=None, display_kind="",
    )

    parent = prepare_continuation_report_parent(
        client=_Client(), client_root=client_root, profile_id="maxa",
        agent_id="research-maxa", work_package_id="wp",
        source_branch_id="source", target_instance_id="target",
        target_branch_id="target",
    )
    assert parent["component_id"] == legacy_id
    publish_checkpoint_snapshot(
        package_root=initialized["package_root"], work_package_id="wp",
        branch_id="target", branch_ref="graph-branch:target:target",
        title="研究", node_id="capability_gap",
        report_parent_id=legacy_id,
        snapshot={
            "assets": [], "gaps": [],
            "sections": [{
                "section_id": "upgrade", "title": "研究图升级",
                "section_role": "upgrade_reentry", "body": "",
                "links": [{
                    "link_id": "checkpoint", "kind": "checkpoint",
                    "target_ref": "trace:upgrade", "label": "升级检查点",
                }], "blocks": [{
                    "kind": "paragraph", "text": "继续既有能力绕行",
                    "link_ids": ["checkpoint"],
                }],
            }],
        },
    )

    saved = load_snapshot(
        package_root=initialized["package_root"], branch_id="target",
    )
    chapters = [item for item in saved["components"]
                if item["kind"] == "chapter"]
    detours = [item for item in saved["components"]
               if item["display_kind"] == "capability_detour"]
    upgrade = next(item for item in saved["components"]
                   if item["display_kind"] == "graph_continuation")
    assert len(chapters) == len(detours) == 1
    assert detours[0]["component_id"] == legacy_id
    assert detours[0]["body"] == "保留既有语义"
    assert detours[0]["content"]["legacy"] is True
    assert upgrade["parent_id"] == legacy_id
    assert any(item["component_id"] == "legacy-entry"
               and item["parent_id"] == legacy_id
               for item in saved["components"])
