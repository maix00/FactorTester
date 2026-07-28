from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import client_research_fork
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.workspace import initialize_work_package


def test_fork_materializes_empty_local_branch_report_tree(
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

    class FakeClient:
        def __init__(self, session) -> None:
            assert session.base_url == "http://127.0.0.1:8141"

        def fork_research_graph_branch(self, instance_id, branch_id, **kwargs):
            assert (instance_id, branch_id) == ("instance-a", "branch-source")
            assert kwargs == {
                "label": "成本假设",
                "acting_profile_ref": "profile:maxa",
            }
            return {"instance_id": "instance-a", "branch_id": "branch-cost"}

    monkeypatch.setattr(
        client_research_fork, "load_profile_root", lambda path: client_root,
    )
    monkeypatch.setattr(client_research_fork, "FactorTesterClient", FakeClient)
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
    assert value["local_report_tree"] == {
        "path": str(branch_root), "status": "materialized",
    }
    assert (branch_root / "sections").is_dir()
    assert not (branch_root / "REPORT.md").exists()
    assert not (branch_root / "JOURNAL.json").exists()
