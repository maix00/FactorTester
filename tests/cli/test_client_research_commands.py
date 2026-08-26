from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import client_research
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile


class _FakeClient:
    def list_profile_research(self, **kwargs):
        assert kwargs == {
            "workspace_ref": "workspace:workspace-a",
            "lifecycle": "active",
            "limit": 7,
            "after": "",
        }
        return {
            "schema_version": 2,
            "items": [{"research_ref": "work-package:instance-a"}],
            "next_cursor": None,
        }

    def get_profile_research(self, research_ref):
        assert research_ref == "work-package:instance-a"
        return {
            "schema_version": 2,
            "work_package_ref": research_ref,
            "branches": [{"branch_ref": "graph-branch:instance-a:b"}],
        }

    def transition_profile_research_lifecycle(
        self,
        work_package_ref,
        **kwargs,
    ):
        assert work_package_ref == "work-package:instance-a"
        assert kwargs == {
            "target": "archived",
            "expected_revision": 1,
            "reason": "pause research",
        }
        return {
            "work_package_ref": work_package_ref,
            "lifecycle": "archived",
            "revision": 2,
        }

    def get_profile_research_branch(self, work_package_ref, branch_id):
        assert (work_package_ref, branch_id) == (
            "work-package:instance-a",
            "branch-1",
        )
        return {
            "branch_ref": "graph-branch:instance-a:branch-1",
            "latest_trace_ref": "trace:current-head",
            "report_checkpoint": {
                "schema_version": 2,
                "checkpoint_ref": "trace:current-head",
            },
        }

    def get_profile_research_report_carrier(
        self, work_package_ref, branch_id, trace_id,
    ):
        assert (work_package_ref, branch_id, trace_id) == (
            "work-package:instance-a", "branch-1", "historical-1",
        )
        return {
            "schema_version": 2,
            "checkpoint_ref": "trace:historical-1",
        }

    def list_profile_research_branch_timeline(
        self,
        work_package_ref,
        branch_id,
        **kwargs,
    ):
        assert (work_package_ref, branch_id, kwargs) == (
            "work-package:instance-a",
            "branch-1",
            {"limit": 9, "after": ""},
        )
        return {"items": [{"step_ref": "trace:1"}], "next_cursor": None}


def test_client_research_list_exposes_stable_json(monkeypatch) -> None:
    monkeypatch.setattr(
        client_research,
        "client_from_config",
        lambda: _FakeClient(),
    )

    result = CliRunner().invoke(cli, [
            "research",
            "workspaces",
        "list",
        "--workspace-ref",
        "workspace:workspace-a",
        "--limit",
        "7",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["items"][0]["research_ref"] == (
        "work-package:instance-a"
    )


def test_client_research_show_returns_work_package(monkeypatch) -> None:
    monkeypatch.setattr(
        client_research,
        "client_from_config",
        lambda: _FakeClient(),
    )

    result = CliRunner().invoke(cli, [
            "research",
            "workspaces",
        "show",
        "work-package:instance-a",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["work_package_ref"] == (
        "work-package:instance-a"
    )


def test_client_research_lifecycle_is_cross_platform(monkeypatch) -> None:
    monkeypatch.setattr(
        client_research,
        "client_from_config",
        lambda: _FakeClient(),
    )

    result = CliRunner().invoke(cli, [
            "research",
            "workspaces",
        "lifecycle",
        "work-package:instance-a",
        "--target",
        "archived",
        "--expected-revision",
        "1",
        "--reason",
        "pause research",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["revision"] == 2


def test_client_research_branch_and_timeline_are_public(monkeypatch) -> None:
    monkeypatch.setattr(
        client_research,
        "client_from_config",
        lambda: _FakeClient(),
    )
    runner = CliRunner()

    branch = runner.invoke(cli, [
        "research", "workspaces", "branch",
        "work-package:instance-a", "branch-1", "--json",
    ])
    timeline = runner.invoke(cli, [
        "research", "workspaces", "timeline",
        "work-package:instance-a", "branch-1",
        "--limit", "9", "--json",
    ])

    assert branch.exit_code == 0, branch.output
    assert timeline.exit_code == 0, timeline.output
    assert json.loads(branch.output)["branch_ref"].endswith(":branch-1")
    assert json.loads(timeline.output)["items"][0]["step_ref"] == "trace:1"


def test_client_research_create_is_profile_scoped_and_records_local_state(
    tmp_path,
    monkeypatch,
) -> None:
    worktree = tmp_path / "factor-worktree"
    worktree.mkdir()
    store = LocalProfileStore(tmp_path)
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "research",
        principal_ref="owner-1",
    )
    profile["workspaces"] = [{
        "workspace_id": "workspace-a",
        "path": str(tmp_path / "research"),
        "access_mode": "owner",
        "owner_ref": "owner-1",
        "server_workspace_ref": "workspace:workspace-a",
    }, {
        "workspace_id": "workspace-z",
        "path": str(tmp_path / "research-z"),
        "access_mode": "owner",
        "owner_ref": "owner-1",
        "server_workspace_ref": "workspace:workspace-z",
    }]
    profile["agents"] = [{
        "agent_id": "research-maxa",
        "role": "research",
        "scope": {"instance_id": "old-instance", "branch_id": "old-branch"},
        "status": "ready",
        "next_action": "Resume the authorized research scope.",
    }]
    profile["factor_workspace_binding"] = {
        "binding_id": "factor-maxa",
        "canonical_repo_ref": "local-factor-git:maxa",
        "base_commit": "a" * 40,
        "branch": "research-maxa",
        "worktree_path": str(worktree),
        "research_root": str(tmp_path / "research"),
        "git_common_dir": str(tmp_path / ".git"),
        "owner_ref": "owner-1",
        "sync_policy": {
            "source_sync_enabled": False,
            "auto_push": False,
            "auto_merge": False,
        },
        "receipt_hash": "receipt",
        "receipt_ref": "file:factor-maxa",
    }
    store.save(profile)

    class FakeClient:
        def get_active_research_graph(self, graph_id):
            assert graph_id == "factor-research"
            return {
                "graph_id": graph_id,
                "entry_node": "hypothesis_preregistration",
                "nodes": [{
                    "node_id": "hypothesis_preregistration",
                    "required_capabilities": ["research-hypothesis.preregister"],
                }],
                "capability_descriptors": {
                    "research-hypothesis.preregister": {
                        "capability_description": "Freeze the hypothesis.",
                        "descriptor_hash": "b" * 64,
                    },
                },
            }

        def create_research_graph_instance(self, **kwargs):
            assert kwargs["profile_ref"] == "profile:maxa"
            assert kwargs["workspace_id"] == "workspace-a"
            assert kwargs["title"] == "MaxA research"
            assert kwargs["capability_resolution"]["node_id"] == (
                "hypothesis_preregistration"
            )
            return {
                "instance_id": "instance-new",
                "work_package_id": "instance-new",
                "branches": [{"branch_id": "branch-new"}],
            }

    monkeypatch.setattr(
        "tools.cli.release.profile_research_create.client_from_config",
        lambda: FakeClient(),
    )
    monkeypatch.setattr(client_research, "load_profile_root", lambda path: tmp_path)
    result = CliRunner().invoke(cli, [
        "research", "workspaces", "create",
        "--profile", "maxa",
        "--title", "MaxA research",
        "--product-group", "core",
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["research"]["work_package_id"] == (
        "instance-new"
    )
    record = store.load("maxa")["research_records"][0]
    assert record["title"] == "MaxA research"
    assert record["graph_instance_ref"] == "work-package:instance-new"
    assert record["graph_branch_ref"] == (
        "graph-branch:instance-new:branch-new"
    )
    package = tmp_path / "research" / "research" / "instance-new"
    assert not (package / "INDEX.json").exists()
    assert not (package / "REPORT.md").exists()
    assert (package / "branches" / "branch-new" / "authoring" / "HEAD.json").exists()
    assert not (package / "branches" / "branch-new" / "REPORT.md").exists()
    assert (package / "branches" / "branch-new" / "authoring" / "HEAD.json").is_file()
    assert not (package / "branches" / "branch-new" / "sections").exists()
    assert not (package / "branches" / "branch-new" / "JOURNAL.json").exists()
    assert not (package / "protocol" / "chapters.json").exists()
    assert record["artifacts"][0]["format"] == "report_tree"
    assert record["artifacts"][0]["local_ref"].endswith(
        "branches/branch-new/authoring/HEAD.json"
    )
    assert (package / ".git").is_dir()


def test_client_research_checkpoint_publish_accepts_bounded_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured = {}
    carrier_path = tmp_path / "checkpoint.json"
    narrative_path = tmp_path / "narrative.json"
    carrier_path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    narrative_path.write_text(
        json.dumps({"language": "zh-Hans"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        client_research,
        "load_profile_root",
        lambda path: tmp_path / "client-root",
    )
    monkeypatch.setattr(
        client_research,
        "publish_research_checkpoint",
        lambda **kwargs: captured.update(kwargs) or {"changed": True},
    )

    result = CliRunner().invoke(cli, [
        "research", "workspaces", "checkpoint", "publish", "maxa",
        "--agent-id", "research-maxa",
        "--checkpoint-file", str(carrier_path),
        "--narrative-file", str(narrative_path),
        "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"changed": True}
    assert captured == {
        "client_root": tmp_path / "client-root",
        "profile_id": "maxa",
        "agent_id": "research-maxa",
        "carrier": {"schema_version": 1},
        "narrative": {"language": "zh-Hans"},
    }


def test_client_research_checkpoint_publish_accepts_stdin(
    monkeypatch,
    tmp_path,
) -> None:
    captured = {}
    narrative_path = tmp_path / "narrative.json"
    narrative_path.write_text(
        json.dumps({"language": "zh-Hans"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        client_research,
        "load_profile_root",
        lambda path: tmp_path / "client-root",
    )
    monkeypatch.setattr(
        client_research,
        "publish_research_checkpoint",
        lambda **kwargs: captured.update(kwargs) or {"changed": False},
    )

    result = CliRunner().invoke(
        cli,
        [
            "research", "workspaces", "checkpoint", "publish", "maxa",
            "--agent-id", "research-maxa",
            "--checkpoint-file", "-",
            "--narrative-file", str(narrative_path),
            "--json",
        ],
        input='{"schema_version": 1}',
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"changed": False}
    assert captured["carrier"] == {"schema_version": 1}
    assert captured["narrative"] == {"language": "zh-Hans"}


def test_client_research_checkpoint_rejects_oversized_input_before_publish(
    monkeypatch,
    tmp_path,
) -> None:
    called = False
    narrative_path = tmp_path / "narrative.json"
    narrative_path.write_text(
        json.dumps({"language": "zh-Hans"}), encoding="utf-8"
    )

    def publish(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(client_research, "publish_research_checkpoint", publish)

    result = CliRunner().invoke(
        cli,
        [
            "research", "workspaces", "checkpoint", "publish", "maxa",
            "--agent-id", "research-maxa",
            "--checkpoint-file", "-",
            "--narrative-file", str(narrative_path),
        ],
        input="x" * (96 * 1024 + 1),
    )

    assert result.exit_code != 0
    assert "exceeds" in result.output
    assert called is False
