from __future__ import annotations

from tools.cli.commands.research_graph_continuation_parent import (
    prepare_continuation_report_parent,
)
from tools.cli.commands.research_graph_continuation_shadow import (
    materialize_shadow_continuation_record,
)
from tools.cli.release.local_profile import (
    LocalProfileStore,
    new_local_profile,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    ensure_node_chapter,
    load_snapshot,
)
from tools.cli.release.research_reporting.workspace import (
    initialize_work_package,
)
from tests.release.report_tree_fixtures import (
    carrier,
    profile as report_profile,
    publish_research_checkpoint,
)


class _Client:
    def get_research_graph_node_info(self, _instance, _branch):
        return {
            "current_node": "hypothesis_preregistration",
            "report_container": {
                "kind": "chapter",
                "anchor_node": "hypothesis_preregistration",
            },
        }


def test_shadow_continuation_keeps_live_scope_and_inherits_report(tmp_path):
    client_root = tmp_path / "client"
    workspace = tmp_path / "workspace"
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=workspace,
    )
    profile["agents"] = [{
        "agent_id": "research-maxa",
        "role": "research",
        "scope": {"instance_id": "source", "branch_id": "source-branch"},
        "status": "ready",
        "next_action": "Resume",
    }]
    profile["research_records"] = [{
        "record_id": "source-wp",
        "title": "动量因子研究",
        "status": "ready",
        "scope": {"factor_families": ["TrMomentum"]},
        "factor_family_versions": ["TrMomentum@1"],
        "agent_id": "research-maxa",
        "created_at": 1,
        "updated_at": 1,
        "workspace_ref": "workspace:one",
        "run_ref": "",
        "graph_instance_ref": "work-package:source-wp",
        "graph_branch_ref": "graph-branch:source:source-branch",
        "checkpoint_ref": "",
        "evidence_refs": [],
        "timeline_refs": [],
        "artifacts": [],
        "provenance": {"kind": "owned_research"},
    }]
    store = LocalProfileStore(client_root)
    store.save(profile)
    initialized = initialize_work_package(
        workspace_root=workspace,
        work_package_id="source-wp",
        branch_id="source-branch",
        workspace_id="one",
        title="动量因子研究",
        branch_ref="graph-branch:source:source-branch",
    )
    chapter = ensure_node_chapter(
        package_root=initialized["package_root"],
        branch_id="source-branch",
        node_id="hypothesis_preregistration",
        title="假设登记",
    )

    record = materialize_shadow_continuation_record(
        client_root=client_root,
        profile_id="maxa",
        agent_id="research-maxa",
        source_instance_id="source",
        source_branch_id="source-branch",
        target_instance_id="shadow",
        target_branch_id="shadow-branch",
        target_work_package_id="shadow-wp",
    )
    parent = prepare_continuation_report_parent(
        client=_Client(),
        client_root=client_root,
        profile_id="maxa",
        agent_id="research-maxa",
        work_package_id="shadow-wp",
        source_work_package_id="source-wp",
        source_branch_id="source-branch",
        target_instance_id="shadow",
        target_branch_id="shadow-branch",
    )

    saved = store.load("maxa")
    assert saved["agents"][0]["scope"] == {
        "instance_id": "source",
        "branch_id": "source-branch",
    }
    assert record["record_id"] == "shadow-wp"
    assert record["source_work_package_id"] == "source-wp"
    assert len(saved["research_records"]) == 2
    snapshot = load_snapshot(
        package_root=workspace / "research" / "shadow-wp",
        branch_id="shadow-branch",
    )
    assert parent["component_id"] == chapter["component_id"]
    assert parent["inherited"] is True
    assert [item["kind"] for item in snapshot["components"]] == ["chapter"]


def test_shadow_record_authorizes_publish_without_retargeting_live_agent(
    tmp_path,
):
    store = report_profile(tmp_path)
    saved = store.load("maxa")
    saved["agents"][0]["scope"] = {
        "instance_id": "live-instance",
        "branch_id": "live-branch",
    }
    saved["research_records"][0]["provenance"] = {
        "kind": "shadow_graph_continuation",
        "source_work_package_id": "live-work-package",
        "source_graph_branch_ref": (
            "graph-branch:live-instance:live-branch"
        ),
    }
    store.save(saved)

    published = publish_research_checkpoint(
        client_root=tmp_path,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier(),
    )

    assert published["checkpoint_ref"] == "trace:checkpoint-1"
    assert store.load("maxa")["agents"][0]["scope"] == {
        "instance_id": "live-instance",
        "branch_id": "live-branch",
    }
