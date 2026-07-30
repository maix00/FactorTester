from __future__ import annotations

from tools.cli.commands.research_graph_local_report import (
    resolve_local_graph_report,
)
from tools.cli.commands.research_graph_report_policy import report_container
from tools.cli.commands.research_graph_report_sync import (
    synchronize_report_container,
)
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    load_snapshot,
)
from tools.cli.release.research_reporting.workspace import initialize_work_package


def _scope(tmp_path):
    client_root, workspace = tmp_path / "client", tmp_path / "workspace"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=workspace,
    )
    profile["research_records"] = [{
        "record_id": "wp", "title": "研究", "status": "pending",
        "scope": {}, "factor_family_versions": [], "agent_id": "agent",
        "created_at": 1, "updated_at": 1, "workspace_ref": "workspace:1",
        "run_ref": "", "graph_instance_ref": "work-package:instance",
        "graph_branch_ref": "graph-branch:instance:branch",
        "checkpoint_ref": "", "evidence_refs": [], "timeline_refs": [],
        "artifacts": [], "provenance": {"kind": "owned_research"},
    }]
    LocalProfileStore(client_root).save(profile)
    initialize_work_package(
        workspace_root=workspace, work_package_id="wp", branch_id="branch",
        workspace_id="1", title="研究",
        branch_ref="graph-branch:instance:branch",
    )
    scope = resolve_local_graph_report(
        client_root=client_root, profile_id="maxa", agent_id="agent",
        instance_id="instance", branch_id="branch",
    )
    return scope, workspace


def _detour(status: str, node: str, trace: str):
    episode = "capability-detour:origin"
    frame = {
        "kind": "special",
        "anchor_node": "hypothesis_preregistration",
        "episode_ref": episode,
    }
    return report_container({
        "current_node": node,
        "report_container": frame,
        "capability_detour": {
            "schema_version": 1, "episode_id": episode, "status": status,
            "resume_node": "hypothesis_preregistration",
            "origin_trace_id": "origin", "latest_trace_id": trace,
            "report_container": frame,
        },
    })


def test_one_detour_episode_reuses_one_special_under_resume_chapter(tmp_path):
    scope, workspace = _scope(tmp_path)
    synchronize_report_container(scope, container=report_container({
        "current_node": "hypothesis_preregistration",
        "report_container": {
            "kind": "chapter",
            "anchor_node": "hypothesis_preregistration",
        },
    }))
    opened = synchronize_report_container(
        scope, container=_detour("opened", "capability_resolution", "t1"),
    )
    retained = synchronize_report_container(
        scope, container=_detour("retained", "capability_gap", "t2"),
    )

    assert opened["component_id"] == retained["component_id"]
    snapshot = load_snapshot(
        package_root=workspace / "research" / "wp", branch_id="branch",
    )
    chapters = [item for item in snapshot["components"]
                if item["kind"] == "chapter"]
    specials = [item for item in snapshot["components"]
                if item["kind"] == "special"]
    assert [item["title"] for item in chapters] == ["假设预注册"]
    assert len(specials) == 1
    assert specials[0]["parent_id"] == chapters[0]["component_id"]
    assert specials[0]["content"]["status"] == "retained"
    assert [row["trace_ref"] for row in specials[0]["content"]["transitions"]] == [
        "trace:t1", "trace:t2",
    ]


def test_bound_legacy_special_is_reused_without_duplicate(tmp_path):
    scope, workspace = _scope(tmp_path)
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
        parent_id=chapter["component_id"], body="保留既有语义",
        content={"legacy": True}, display_kind="capability_resolution",
        bindings=[{
            "binding_id": "legacy-detour-binding",
            "kind": "graph_reference",
            "target_ref": "capability-detour:origin",
            "label": "能力修复过程",
            "data": {"role": "capability_detour"},
        }],
    )
    result = synchronize_report_container(
        scope, container=_detour("retained", "capability_gap", "t2"),
    )
    snapshot = load_snapshot(
        package_root=workspace / "research" / "wp", branch_id="branch",
    )
    specials = [item for item in snapshot["components"]
                if item["kind"] == "special"]
    assert result["component_id"] == legacy_id
    assert len(specials) == 1
    assert specials[0]["body"] == "保留既有语义"
    assert specials[0]["content"]["legacy"] is True
