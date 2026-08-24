from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import client_research_fork
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    load_snapshot,
)
from tools.cli.release.research_reporting.workspace import initialize_work_package


def test_fork_inherits_source_report_tree(
    tmp_path: Path, monkeypatch,
) -> None:
    client_root = tmp_path / "client"
    workspace_root = tmp_path / "workspace"
    store = LocalProfileStore(client_root)
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=workspace_root,
    )
    profile["research_records"] = [{
        "record_id": "package-a",
        "title": "研究 A",
        "status": "pending",
        "scope": {"factor_families": ["SgCCS"]},
        "factor_family_versions": ["MaxA:SgCCS@1"],
        "agent_id": "research-maxa",
        "created_at": 1.0,
        "updated_at": 1.0,
        "workspace_ref": "workspace:workspace-a",
        "run_ref": "",
        "graph_instance_ref": "work-package:package-a",
        "graph_branch_ref": "graph-branch:instance-a:branch-source",
        "checkpoint_ref": "",
        "evidence_refs": [],
        "timeline_refs": [],
        "artifacts": [],
        "provenance": {"kind": "owned_research"},
    }]
    store.save(profile)
    initialize_work_package(
        workspace_root=workspace_root,
        work_package_id="package-a",
        branch_id="branch-source",
        workspace_id="workspace-a",
        title="研究 A",
        branch_ref="graph-branch:instance-a:branch-source",
    )
    package_root = workspace_root / "research" / "package-a"
    add_component(
        package_root=package_root,
        branch_id="branch-source",
        component_id="chapter-a",
        kind="chapter",
        title="假设登记",
        parent_id=None,
        body=r"信号为 \(r_t\)",
        content=None,
        display_kind="",
        bindings=[{
            "binding_id": "evidence-a",
            "kind": "evidence",
            "target_ref": "evidence:a",
            "label": "样本证据",
            "data": {},
        }],
    )

    class FakeClient:
        pass

        def fork_research_graph_branch(self, instance_id, branch_id, **kwargs):
            assert (instance_id, branch_id) == ("instance-a", "branch-source")
            assert kwargs == {
                "label": "成本假设",
                "acting_profile_ref": "profile:maxa",
            }
            return {"instance_id": "instance-a", "branch_id": "branch-cost"}

        def get_research_graph_node_info(self, instance_id, branch_id):
            assert (instance_id, branch_id) == (
                "instance-a", "branch-cost",
            )
            return {
                "graph": "factor-research@v10",
                "node": {"node_id": "hypothesis_preregistration"},
                "context_ref": "sha256:" + "1" * 64,
                "checkpoint_ref": "trace:fork",
                "current_obligations": [],
                "entry_requirements": [],
            }

    monkeypatch.setattr(
        client_research_fork, "load_profile_root", lambda path: client_root,
    )
    monkeypatch.setattr(
        client_research_fork, "client_from_config", lambda: FakeClient(),
    )
    result = CliRunner().invoke(cli, [
        "client", "research", "fork",
        "graph-branch:instance-a:branch-source",
        "--profile", "maxa",
        "--label", "成本假设",
    ])

    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    branch_root = (
        workspace_root / "research" / "package-a" / "branches" / "branch-cost"
    )
    local = value["local_report_tree"]
    assert local["path"] == str(branch_root)
    assert local["status"] == "inherited"
    assert local["source_branch_id"] == "branch-source"
    assert local["commit"]
    assert not (branch_root / "sections").exists()
    assert (branch_root / "REPORT.md").is_file()
    assert not (branch_root / "JOURNAL.json").exists()
    source = load_snapshot(
        package_root=package_root, branch_id="branch-source",
    )
    target = load_snapshot(
        package_root=package_root, branch_id="branch-cost",
    )
    assert target["components"] == source["components"]
    assert target["bindings"] == source["bindings"]
    assert target["head"]["root_ref"] == source["head"]["root_ref"]
    assert target["head"]["report_id"] == "report-package-a-branch-cost"
    saved = store.load("maxa")
    assert len(saved["research_records"]) == 1
    assert {
        item["branch_ref"]
        for item in saved["research_records"][0]["branch_bindings"]
    } == {
        "graph-branch:instance-a:branch-source",
        "graph-branch:instance-a:branch-cost",
    }
