from __future__ import annotations
import json
from click.testing import CliRunner
from tools.cli.app import cli
from tools.cli.commands import research_graph_navigation as navigation
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_obligations import (
    canonicalize_ledger,
    initialize_ledger,
    ledger_path,
    load_ledger,
    write_ledger,
)
from tools.cli.release.research_reporting.authoring.tree_model import load_snapshot
from tools.cli.release.research_reporting.git import commit_work_package
from tools.cli.release.research_reporting.workspace import initialize_work_package

class _Client:
    def __init__(self, targets: list[str]) -> None:
        self.targets = targets
        self.advance_calls = 0

    def get_research_graph_node_info(self, _instance, _branch):
        current = (
            "hypothesis_preregistration"
            if self.advance_calls == 0
            else self.targets[min(
                self.advance_calls - 1, len(self.targets) - 1
            )]
        )
        return {
            "graph": "factor-research@v10",
            "node": {"node_id": current},
            "branch": {"current_owner_profile_ref": "profile:maxa"},
            "context_ref": "sha256:" + "1" * 64,
            "checkpoint_ref": f"trace:checkpoint-{self.advance_calls}",
            "current_obligations": [],
            "entry_requirements": [],
            "report_container": {
                "kind": "chapter",
                "anchor_node": current,
            },
            "next_actions": [],
        }

    def get_research_graph_edge_info(self, _instance, _branch, _edge):
        return {
            "state_ref": "",
            "edge": {
                "edge_id": "edge-1",
                "to_node": self.targets[0],
                "obligation_requirements": [],
            },
            "report_requirements": [],
        }

    def advance_research_graph_node(self, *_args, **_kwargs):
        target = self.targets[min(self.advance_calls, len(self.targets) - 1)]
        self.advance_calls += 1
        return {
            "current_node": target,
            "latest_trace_id": f"accepted-{self.advance_calls}",
            # The advance response describes the completed transition and may
            # retain its source container.  The follow-up node packet above is
            # authoritative for the chapter that must become current.
            "report_container": {
                "kind": "chapter",
                "anchor_node": "hypothesis_preregistration",
            },
        }


def _local_research(tmp_path, *, include_record: bool = True):
    client_root, workspace = tmp_path / "client", tmp_path / "workspace"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=workspace,
    )
    if include_record:
        profile["research_records"] = [{
            "record_id": "wp-1", "title": "动量因子研究", "status": "pending",
            "scope": {}, "factor_family_versions": [],
            "agent_id": "research-maxa", "created_at": 1, "updated_at": 1,
            "workspace_ref": "workspace:1", "run_ref": "",
            "graph_instance_ref": "work-package:wp-1",
            "graph_branch_ref": "graph-branch:instance-1:branch-1",
            "checkpoint_ref": "", "evidence_refs": [], "timeline_refs": [],
            "artifacts": [], "provenance": {"kind": "owned_research"},
        }]
        initialize_work_package(
            workspace_root=workspace, work_package_id="wp-1",
            branch_id="branch-1", workspace_id="1", title="动量因子研究",
            branch_ref="graph-branch:instance-1:branch-1",
        )
    LocalProfileStore(client_root).save(profile)
    return client_root, workspace


def _invoke(monkeypatch, tmp_path, client, *, acting=True):
    client_root, workspace = _local_research(tmp_path)
    package = workspace / "research" / "wp-1"
    packet = client.get_research_graph_node_info("instance-1", "branch-1")
    path = ledger_path(package, "branch-1")
    ledger = (
        load_ledger(package, "branch-1")
        if path.is_file()
        else initialize_ledger(
            branch_ref="graph-branch:instance-1:branch-1",
            graph_ref=str(packet["graph"]),
            current_node=str(packet["node"]["node_id"]),
            context_ref=str(packet["context_ref"]),
            checkpoint_ref=str(packet["checkpoint_ref"]),
        )
    )
    ledger["current_projection"]["selected_edge"] = {
        "edge_id": "edge-1",
        "target_node": client.targets[0],
        "state_ref": "",
        "transition_contract": {
            "edge_id": "edge-1",
            "to_node": client.targets[0],
            "obligation_requirements": [],
        },
        "required_requirement_ids": [],
    }
    write_ledger(
        package, "branch-1", canonicalize_ledger(ledger),
    )
    commit_work_package(package, message="Select test Graph edge")
    monkeypatch.setattr(navigation, "load_profile_root", lambda _path: client_root)
    monkeypatch.setattr(navigation, "client_from_config", lambda: client)
    monkeypatch.setattr(navigation, "_client_for_profile", lambda *_args: client)
    monkeypatch.setattr(
        navigation, "_current_branch_report_submission",
        lambda **_kwargs: {"schema_version": 1, "items": []},
    )
    evidence = tmp_path / f"evidence-{client.advance_calls}.json"
    evidence.write_text('{"ready": true}', encoding="utf-8")
    args = [
        "research", "graphs", "node", "advance", "instance-1", "branch-1",
        "--edge-id", "edge-1", "--evidence-file", str(evidence),
    ]
    if acting:
        args += ["--acting-profile-ref", "profile:maxa"]
    result = CliRunner().invoke(cli, args)
    return result, workspace


def test_acting_profile_only_advance_creates_target_chapter(monkeypatch, tmp_path):
    client = _Client(["data_contract"])
    result, workspace = _invoke(monkeypatch, tmp_path, client)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    sync = payload["local_report_publish"]["chapter_sync"]
    assert sync["node_id"] == "data_contract"
    assert sync["created_count"] == 0
    assert sync["existing_count"] == 1
    snapshot = load_snapshot(
        package_root=workspace / "research" / "wp-1", branch_id="branch-1",
    )
    assert [
        item["title"] for item in snapshot["components"]
        if item["kind"] == "chapter"
    ] == [
        "假设预注册", "数据契约",
    ]


def test_repeated_node_visit_reuses_stable_chapter(monkeypatch, tmp_path):
    client = _Client(["data_contract"])
    first, workspace = _invoke(monkeypatch, tmp_path, client)
    assert first.exit_code == 0, first.output
    second, _ = _invoke(monkeypatch, tmp_path, client, acting=False)
    assert second.exit_code == 0, second.output
    snapshot = load_snapshot(
        package_root=workspace / "research" / "wp-1", branch_id="branch-1",
    )
    assert [
        item["title"] for item in snapshot["components"]
        if item["kind"] == "chapter"
    ] == [
        "假设预注册", "数据契约",
    ]


def test_bound_profile_without_branch_record_blocks_before_advance(
    monkeypatch, tmp_path,
):
    client_root, _ = _local_research(tmp_path, include_record=False)
    client = _Client(["data_contract"])
    monkeypatch.setattr(navigation, "load_profile_root", lambda _path: client_root)
    monkeypatch.setattr(navigation, "_client_for_profile", lambda *_args: client)
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"ready": true}', encoding="utf-8")
    result = CliRunner().invoke(cli, [
        "research", "graphs", "node", "advance", "instance-1", "branch-1",
        "--edge-id", "edge-1", "--evidence-file", str(evidence),
        "--acting-profile-ref", "profile:maxa",
    ])
    assert result.exit_code != 0
    assert "local research record" in result.output
    assert client.advance_calls == 0
