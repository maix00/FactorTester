from __future__ import annotations

from tools.cli.commands.research_graph_continuation_parent import (
    prepare_continuation_report_parent,
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


class _Client:
    def get_research_graph_node_info(self, _instance, _branch):
        return {
            "graph": "factor-research@v10",
            "node": {"node_id": "hypothesis_preregistration"},
            "current_node": "hypothesis_preregistration",
            "context_ref": "sha256:" + "1" * 64,
            "checkpoint_ref": "trace:target",
            "current_obligations": [],
            "entry_requirements": [],
            "report_container": {
                "kind": "chapter",
                "anchor_node": "hypothesis_preregistration",
            },
        }


def _profile(client_root, workspace):
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=workspace,
    )
    profile["agents"] = [{
        "agent_id": "research-maxa", "role": "research",
        "scope": {"instance_id": "target", "branch_id": "target"},
        "status": "ready", "next_action": "Resume",
    }]
    profile["research_records"] = [{
        "record_id": "wp", "title": "研究", "status": "ready",
        "scope": {"factor_families": ["SgCCS"]},
        "factor_family_versions": ["SgCCS@1"],
        "agent_id": "research-maxa", "created_at": 1, "updated_at": 1,
        "workspace_ref": "workspace:one", "run_ref": "",
        "graph_instance_ref": "work-package:wp",
        "graph_branch_ref": "graph-branch:target:target",
        "checkpoint_ref": "", "evidence_refs": [], "timeline_refs": [],
        "artifacts": [], "provenance": {"kind": "owned_research"},
    }]
    LocalProfileStore(client_root).save(profile)


def test_continuation_without_detour_reuses_substantive_chapter(tmp_path):
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

    first = prepare_continuation_report_parent(
        client=_Client(), client_root=client_root, profile_id="maxa",
        agent_id="research-maxa", work_package_id="wp",
        source_branch_id="source", target_instance_id="target",
        target_branch_id="target",
    )
    repeated = prepare_continuation_report_parent(
        client=_Client(), client_root=client_root, profile_id="maxa",
        agent_id="research-maxa", work_package_id="wp",
        source_branch_id="source", target_instance_id="target",
        target_branch_id="target",
    )

    snapshot = load_snapshot(
        package_root=initialized["package_root"], branch_id="target",
    )
    assert first["component_id"] == chapter["component_id"]
    assert first["inherited"] is True
    assert repeated["inherited"] is False
    assert [item["kind"] for item in snapshot["components"]] == ["chapter"]
