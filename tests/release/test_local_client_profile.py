from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.client import FactorTesterClient
from tools.cli.http import HttpSession
from tools.cli.release.adapters.profile_binding import adapter_binding
from tools.cli.release.local_profile import (
    LocalProfileStore,
    new_local_profile,
    validate_local_profile,
)


def test_local_profile_is_strict_private_and_version_independent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = LocalProfileStore(root)
    profile = new_local_profile(
        profile_id="research-a",
        display_name="Research A",
        server_url="http://127.0.0.1:8123/",
        workspace_root=tmp_path / "workspace",
    )
    stored = store.save(profile)

    assert "server" not in stored
    assert store.load("research-a") == stored
    path = root / "profiles" / "research-a.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert not (root / "current.json").exists()
    assert not {"password", "token", "email"}.intersection(stored)
    assert stored["schema_version"] == 10
    assert stored["status"] == "active"
    assert stored["workspaces"] == []
    assert stored["initialization_sources"] == []
    assert stored["session_binding"] == {}
    assert stored["research_records"] == []
    assert stored["factor_workspace_binding"] == {}

    with pytest.raises(ValueError, match="fields"):
        validate_local_profile({**stored, "token": "must-not-be-stored"})
    with pytest.raises(ValueError, match="must not contain server"):
        validate_local_profile({
            **stored, "server": {"base_url": "http://127.0.0.1:8000"},
        })


def test_loading_profile_migrates_legacy_research_identity_once(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = LocalProfileStore(root)
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
    )
    profile["research_records"] = [{
        "record_id": "work-package-1",
        "title": "研究",
        "status": "pending",
        "scope": {},
        "factor_family_versions": [],
        "agent_id": "research-maxa",
        "created_at": 1.0,
        "updated_at": 1.0,
        "workspace_ref": "",
        "run_ref": "",
        "graph_instance_ref": "graph-instance:physical-1",
        "graph_branch_ref": "graph-branch:branch-1",
        "checkpoint_ref": "",
        "evidence_refs": [],
        "artifacts": [],
        "provenance": {},
        "timeline_refs": [],
    }]
    store.save(profile)

    migrated = store.load("maxa")
    record = migrated["research_records"][0]
    assert record["graph_instance_ref"] == "work-package:work-package-1"
    assert record["graph_branch_ref"] == (
        "graph-branch:physical-1:branch-1"
    )
    assert store.load("maxa") == migrated


def test_graph_upgrade_retargets_one_stable_work_package_record(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = LocalProfileStore(root)
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
        principal_ref="18717974771",
    )
    profile["agents"] = [{
        "agent_id": "research-maxa",
        "role": "research",
        "scope": {"instance_id": "physical-v6", "branch_id": "branch-v6"},
        "status": "ready",
        "next_action": "Resume the authorized research scope.",
    }]
    stable = {
        "record_id": "sgccs-work-package",
        "title": "SgCCS research",
        "status": "ready",
        "scope": {"factor_families": ["SgCCS"]},
        "factor_family_versions": ["SgCCS@6"],
        "agent_id": "research-maxa",
        "created_at": 1.0,
        "updated_at": 2.0,
        "workspace_ref": "workspace:sgccs",
        "run_ref": "run:v6",
        "graph_instance_ref": "work-package:sgccs-work-package",
        "graph_branch_ref": "graph-branch:physical-v6:branch-v6",
        "checkpoint_ref": "trace:v6",
        "evidence_refs": ["evidence:v6"],
        "timeline_refs": [],
        "artifacts": [],
        "provenance": {"kind": "owned_research"},
    }
    duplicate = {
        **stable,
        "record_id": "physical-v7",
        "title": "SgCCS auxiliary-signal research",
        "factor_family_versions": ["SgCCS@7"],
        "updated_at": 3.0,
        "run_ref": "",
        "graph_instance_ref": "work-package:physical-v7",
        "graph_branch_ref": "graph-branch:physical-v7:branch-v7",
        "checkpoint_ref": "trace:v7",
        "evidence_refs": ["evidence:v7"],
        "artifacts": [{
            "artifact_ref": (
                "artifact:research/physical-v7/branches/branch-v7/REPORT.md"
            ),
            "format": "markdown",
            "status": "ready",
            "content_hash": "abc",
            "local_ref": (
                tmp_path / "workspace" / "research" / "physical-v7"
                / "branches" / "branch-v7" / "REPORT.md"
            ).as_uri(),
            "index_ref": (
                tmp_path / "workspace" / "research" / "physical-v7"
                / "INDEX.json"
            ).as_uri(),
            "journal_ref": (
                tmp_path / "workspace" / "research" / "physical-v7"
                / "branches" / "branch-v7" / "JOURNAL.json"
            ).as_uri(),
            "journal_hash": "a" * 64,
            "section_refs": [],
        }],
        "provenance": {"kind": "active_graph_research"},
    }
    profile["research_records"] = [stable, duplicate]
    store.save(profile)

    saved = store.retarget_research_incarnation(
        "maxa",
        agent_id="research-maxa",
        work_package_id="sgccs-work-package",
        source_instance_id="physical-v6",
        source_branch_id="branch-v6",
        target_instance_id="physical-v7",
        target_branch_id="branch-v7",
    )

    assert saved["agents"][0]["scope"] == {
        "instance_id": "physical-v7",
        "branch_id": "branch-v7",
    }
    assert len(saved["research_records"]) == 1
    record = saved["research_records"][0]
    assert record["record_id"] == "sgccs-work-package"
    assert record["graph_instance_ref"] == (
        "work-package:sgccs-work-package"
    )
    assert record["graph_branch_ref"] == (
        "graph-branch:physical-v7:branch-v7"
    )
    assert record["factor_family_versions"] == ["SgCCS@6", "SgCCS@7"]
    assert record["created_at"] == 1.0
    assert record["updated_at"] == 3.0
    assert record["checkpoint_ref"] == "trace:v7"
    assert record["evidence_refs"] == ["evidence:v6", "evidence:v7"]
    artifact = record["artifacts"][0]
    assert artifact["artifact_ref"].startswith(
        "artifact:research/physical-v7/"
    )
    assert "/research/physical-v7/" in artifact["local_ref"]
    assert "/research/physical-v7/" in artifact["journal_ref"]

    repeated = store.retarget_research_incarnation(
        "maxa",
        agent_id="research-maxa",
        work_package_id="sgccs-work-package",
        source_instance_id="physical-v6",
        source_branch_id="branch-v6",
        target_instance_id="physical-v7",
        target_branch_id="branch-v7",
    )
    assert repeated == saved


def test_client_cli_exposes_generic_profile_and_adapter_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "client-support"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    import tools.cli.commands.client_profile as command_module

    monkeypatch.setattr(
        command_module,
        "_sync_profile",
        lambda _profile, *, manager_url="": {
            "status": "pending",
            "synced": False,
            "pending": True,
            "manager_url": manager_url,
        },
    )
    runner = CliRunner()

    result = runner.invoke(cli, [
        "client", "profile", "create",
        "--profile-id", "research-a",
        "--display-name", "Research A",
        "--server-url", "http://127.0.0.1:8123",
        "--principal-ref", "18717974771",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["profile"]["profile_id"] == "research-a"
    workspace = (
        tmp_path / "Documents/FactorTester/users/18717974771"
        / "profiles/research-a"
    )
    assert workspace.is_dir()
    assert workspace.stat().st_mode & 0o777 == 0o700
    repeated = runner.invoke(cli, [
        "client", "profile", "create",
        "--profile-id", "research-a",
        "--display-name", "Research A",
        "--server-url", "http://127.0.0.1:8123",
        "--principal-ref", "18717974771",
    ])
    assert repeated.exit_code == 0, repeated.output
    assert runner.invoke(cli, ["client", "profile", "list"]).exit_code == 0
    adapters = runner.invoke(cli, ["client", "adapter", "list"])
    assert adapters.exit_code == 0
    assert json.loads(adapters.output) == []


def test_profile_server_update_uses_public_cli_and_preserves_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "client-support"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    store = LocalProfileStore(root)
    original = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8000",
        workspace_root=tmp_path / "workspace",
        principal_ref="18717974771",
    )
    store.save(original)

    result = CliRunner().invoke(cli, [
        "client", "profile", "server", "set", "maxa",
        "--server-url", "http://127.0.0.1:8141/",
    ])

    assert result.exit_code == 0, result.output
    updated = json.loads(result.output)
    assert updated["connection_scope"] == "client"
    assert updated["base_url"] == "http://127.0.0.1:8141"
    assert updated["profile_id"] == original["profile_id"]
    unchanged = LocalProfileStore(root).load("maxa")
    assert unchanged["session_binding"] == original["session_binding"]
    assert unchanged["workspace_root"] == original["workspace_root"]
    assert "server" not in unchanged


def test_profile_workspace_bind_and_list_use_compact_local_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "client-support"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(root))
    store = LocalProfileStore(root)
    store.save(new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
        principal_ref="18717974771",
    ))
    runner = CliRunner()

    bound = runner.invoke(cli, [
        "client", "profile", "workspace", "bind", "maxa",
        "--workspace-id", "sgccs-research",
        "--server-workspace-ref", "workspace:eb086",
        "--access-mode", "owner",
        "--owner-ref", "18717974771",
    ])
    listed = runner.invoke(cli, [
        "client", "profile", "workspace", "list", "maxa",
    ])

    assert bound.exit_code == 0, bound.output
    workspace = json.loads(bound.output)["workspaces"][0]
    assert workspace == {
        "workspace_id": "sgccs-research",
        "path": str(tmp_path / "workspace"),
        "access_mode": "owner",
        "owner_ref": "18717974771",
        "server_workspace_ref": "workspace:eb086",
    }
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output) == [workspace]


def test_profile_agent_set_derives_ready_state_from_bound_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "client-support"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(root))
    store = LocalProfileStore(root)
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
        principal_ref="18717974771",
    )
    profile["workspaces"] = [{
        "workspace_id": "sgccs-research",
        "path": str(tmp_path / "workspace"),
        "access_mode": "owner",
        "owner_ref": "18717974771",
        "server_workspace_ref": "workspace:eb086",
    }]
    store.save(profile)

    result = CliRunner().invoke(cli, [
        "client", "profile", "agent", "set", "maxa",
        "--agent-id", "planning-maxa",
        "--role", "planning",
        "--workspace-id", "sgccs-research",
    ])

    assert result.exit_code == 0, result.output
    agent = json.loads(result.output)["agents"][0]
    assert agent["scope"] == {"workspace_id": "sgccs-research"}
    assert agent["status"] == "ready"
    assert agent["next_action"] == "Resume the authorized research scope."


def test_profile_claim_does_not_treat_unknown_workspace_as_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "client-support"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(root))
    store = LocalProfileStore(root)
    store.save(new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
        principal_ref="18717974771",
    ))
    runner = CliRunner()
    configured = runner.invoke(cli, [
        "client", "profile", "agent", "set", "maxa",
        "--agent-id", "planning-maxa",
        "--role", "planning",
        "--workspace-id", "unknown-workspace",
    ])

    claim = runner.invoke(cli, [
        "client", "profile", "claim", "maxa", "planning-maxa",
    ])

    assert configured.exit_code == 0, configured.output
    assert json.loads(configured.output)["agents"][0]["status"] == (
        "needs_scope"
    )
    assert claim.exit_code == 0, claim.output
    assert json.loads(claim.output)["research_execution_scope_bound"] is False


def test_profile_workspace_remove_downgrades_scoped_planning_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "client-support"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(root))
    store = LocalProfileStore(root)
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
        principal_ref="18717974771",
    )
    profile["workspaces"] = [{
        "workspace_id": "sgccs-research",
        "path": str(tmp_path / "workspace"),
        "access_mode": "owner",
        "owner_ref": "18717974771",
        "server_workspace_ref": "workspace:eb086",
    }]
    profile["agents"] = [{
        "agent_id": "planning-maxa",
        "role": "planning",
        "scope": {"workspace_id": "sgccs-research"},
        "status": "ready",
        "next_action": "Resume the authorized research scope.",
    }]
    store.save(profile)

    result = CliRunner().invoke(cli, [
        "client", "profile", "workspace", "remove", "maxa",
        "sgccs-research",
    ])

    assert result.exit_code == 0, result.output
    updated = json.loads(result.output)
    assert updated["workspaces"] == []
    agent = updated["agents"][0]
    assert agent["scope"] == {"workspace_id": "unbound"}
    assert agent["status"] == "needs_scope"
    assert agent["next_action"] == (
        "Bind an authorized research scope before execution."
    )


def test_version_one_profile_is_upgraded_without_losing_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    path = root / "profiles" / "legacy.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "schema_version": 1,
        "profile_id": "legacy",
        "display_name": "Legacy",
        "server": {"base_url": "http://127.0.0.1:8123"},
        "workspace_root": str(tmp_path / "legacy"),
        "agents": [],
        "adapters": [],
    }))

    upgraded = LocalProfileStore(root).load("legacy")

    assert upgraded["schema_version"] == 10
    assert upgraded["status"] == "active"
    assert upgraded["profile_id"] == "legacy"
    assert upgraded["workspaces"] == []
    assert upgraded["initialization_sources"] == []
    assert "server" not in upgraded
    persisted = json.loads(path.read_text())
    assert "server" not in persisted


def test_bootstrap_claims_isolated_agents_with_shared_library_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.cli.commands.client_profile as command_module

    root = tmp_path / "client-support"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        FactorTesterClient,
        "current_principal",
        lambda self: {"username": "18717974771"},
    )
    monkeypatch.setattr(
        FactorTesterClient,
        "factor_library_sources",
        lambda self: {
            "principal": "18717974771",
            "sources": [{
                "owner_ref": "18717974771",
                "owner_alias": "18717974771",
                "factor_count": 1,
            }],
        },
    )
    monkeypatch.setattr(
        FactorTesterClient,
        "factor_library_source_projection",
        lambda self, owner_ref: {
            "projection": {
                "schema_version": 1,
                "principal": "18717974771",
                "owner_ref": owner_ref,
                "factors": [{"factor_alias": "SgCCS"}],
            },
            "projection_hash": "a" * 64,
        },
    )
    monkeypatch.setattr(
        command_module,
        "_sync_profile",
        lambda _profile, *, manager_url="": {
            "status": "pending",
            "synced": False,
            "pending": True,
            "manager_url": manager_url,
        },
    )
    runner = CliRunner()

    for profile_id, agent_id in (
        ("maxa", "research-maxa"),
        ("maxb", "research-maxb"),
    ):
        result = runner.invoke(cli, [
            "client", "profile", "bootstrap",
            "--profile-id", profile_id,
            "--display-name", profile_id.upper(),
            "--server-url", "http://127.0.0.1:8000",
            "--agent-id", agent_id,
            "--principal-ref", "18717974771",
        ])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["local_profile_claimed"]
        assert not payload["local_source_registered"]
        assert payload["server_visibility_verified"]
        assert payload["ready"] is False
        assert payload["can_start_inspection_and_planning"] is True
        assert payload["claim_command"] == (
            f"factortester client profile claim {profile_id} {agent_id}"
        )
        assert "Codex" not in payload["agent_prompt"]
        receipt = payload["claim_receipt"]
        assert receipt["schema_version"] == 2
        assert receipt["can_start_inspection_and_planning"] is True
        assert receipt["research_execution_scope_bound"] is False
        assert receipt["factor_worktree_ref"] == ""
        assert receipt["factor_worktree_path"] == ""
        assert receipt["factor_worktree_branch"] == ""
        assert receipt["factor_worktree_commit"] == ""
        assert receipt["factor_worktree_commit_kind"] == ""
        assert receipt["factor_worktree_available"] is False
        assert receipt["canonical_repo_ref"] == ""
        assert receipt["sync_policy"] == {}
        assert receipt["recommended_cwd"] == receipt["workspace_root"]
        assert receipt["next_command"] == (
            f"factortester factor-library profile create {profile_id}"
        )
        assert "profile" not in {
            key.lower() for key in receipt if key != "profile_id"
        }
        assert Path(receipt["workspace_root"]).stat().st_mode & 0o777 == 0o700
        profile = payload["profile"]
        assert profile["profile_id"] == profile_id
        assert profile["agents"][0]["agent_id"] == agent_id
        assert profile["session_binding"]["principal_ref"] == "18717974771"
        assert profile["initialization_sources"] == []
        bound = runner.invoke(cli, [
            "client", "profile", "initialization", "bind", profile_id,
            "--owner-ref", "18717974771",
        ])
        assert bound.exit_code == 0, bound.output
        profile = json.loads(bound.output)
        source = profile["initialization_sources"][0]
        assert source["owner_ref"] == "18717974771"
        assert source["mode"] == "reference"
        assert source["source_ref"].endswith("/18717974771")
        assert source["principal_ref"] == "18717974771"
        assert source["projection_hash"] == "a" * 64
        assert source["source_materialized"] is False
        assert source["session_ref"].startswith(
            "session-binding://18717974771/"
        )
        assert not {"password", "token"}.intersection(source)
        claimed = runner.invoke(cli, [
            "client", "profile", "claim", profile_id, agent_id,
        ])
        assert claimed.exit_code == 0, claimed.output
        updated_receipt = json.loads(claimed.output)
        assert updated_receipt["receipt_hash"] != receipt["receipt_hash"]
        receipt_path = Path(
            updated_receipt["receipt_ref"].removeprefix("file://")
        )
        before_mtime = receipt_path.stat().st_mtime_ns
        repeated_claim = runner.invoke(cli, [
            "client", "profile", "claim", profile_id, agent_id,
        ])
        assert repeated_claim.exit_code == 0, repeated_claim.output
        assert json.loads(repeated_claim.output)["receipt_hash"] == (
            updated_receipt["receipt_hash"]
        )
        assert receipt_path.stat().st_mtime_ns == before_mtime

    maxa = LocalProfileStore(root).load("maxa")
    maxb = LocalProfileStore(root).load("maxb")
    assert maxa["workspace_root"] != maxb["workspace_root"]
    assert Path(maxa["workspace_root"]).is_dir()
    assert Path(maxb["workspace_root"]).is_dir()
    assert maxa["agents"] != maxb["agents"]
    assert maxa["initialization_sources"][0]["session_ref"] != (
        maxb["initialization_sources"][0]["session_ref"]
    )


def test_claim_receipt_exposes_compact_bound_factor_worktree(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    workspace = tmp_path / "profile"
    worktree = workspace / "factor-worktrees" / "maxa"
    worktree.mkdir(parents=True)
    subprocess.run(
        ["git", "-C", str(worktree), "init", "-b", "agent/maxa"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(worktree), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(worktree), "config", "user.name", "Tests"],
        check=True,
    )
    (worktree / "Factor.py").write_text("value = 1\n")
    subprocess.run(
        ["git", "-C", str(worktree), "add", "Factor.py"], check=True
    )
    subprocess.run(
        ["git", "-C", str(worktree), "commit", "-m", "base"],
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    store = LocalProfileStore(root)
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8000",
        workspace_root=workspace,
    )
    profile["agents"] = [{
        "agent_id": "research-maxa",
        "role": "research",
        "scope": {"instance_id": "i-1", "branch_id": "b-1"},
        "status": "ready",
        "next_action": "Continue research.",
    }]
    profile["factor_workspace_binding"] = {
        "binding_id": "factor-worktree-test",
        "canonical_repo_ref": "local-factor-git://canonical/test",
        "base_commit": head,
        "branch": "agent/maxa",
        "worktree_path": str(worktree),
        "research_root": str(workspace / "research"),
        "git_common_dir": str(worktree / ".git"),
        "owner_ref": "maxa",
        "sync_policy": {
            "source_sync_enabled": False,
            "auto_push": False,
            "auto_merge": False,
        },
        "receipt_hash": "a" * 64,
        "receipt_ref": (tmp_path / "binding.json").resolve().as_uri(),
    }
    store.save(profile)

    first = store.claim_agent("maxa", "research-maxa")
    receipt_path = Path(first["receipt_ref"].removeprefix("file://"))
    before_mtime = receipt_path.stat().st_mtime_ns
    second = store.claim_agent("maxa", "research-maxa")

    assert second == first
    assert receipt_path.stat().st_mtime_ns == before_mtime
    assert first["factor_worktree_ref"].endswith("binding.json")
    assert first["factor_worktree_path"] == str(worktree)
    assert first["factor_worktree_branch"] == "agent/maxa"
    assert first["factor_worktree_commit"] == head
    assert first["factor_worktree_commit_kind"] == "head"
    assert first["factor_worktree_available"] is True
    assert first["canonical_repo_ref"] == "local-factor-git://canonical/test"
    assert first["sync_policy"]["auto_push"] is False
    assert first["recommended_cwd"] == str(worktree)
    assert first["next_command"] == ""
    assert "profile" not in first
    assert len(json.dumps(first)) < 2_500

    (worktree / "Factor.py").write_text("value = 2\n")
    subprocess.run(
        ["git", "-C", str(worktree), "add", "Factor.py"], check=True
    )
    subprocess.run(
        ["git", "-C", str(worktree), "commit", "-m", "advance"],
        check=True,
        capture_output=True,
    )
    advanced = store.claim_agent("maxa", "research-maxa")
    assert advanced["factor_worktree_commit"] != head
    assert advanced["receipt_hash"] != first["receipt_hash"]


def test_bootstrap_fails_closed_before_local_write_on_principal_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "client-support"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(root))
    monkeypatch.setattr(
        FactorTesterClient,
        "current_principal",
        lambda self: {"username": "someone-else"},
    )

    result = CliRunner().invoke(cli, [
        "client", "profile", "bootstrap",
        "--profile-id", "maxa",
        "--display-name", "MaxA",
        "--server-url", "http://127.0.0.1:8000",
        "--agent-id", "research-maxa",
        "--principal-ref", "18717974771",
    ])

    assert result.exit_code != 0
    assert "does not match" in result.output
    assert not (root / "profiles").exists()


def test_bootstrap_does_not_rebind_existing_profile_to_new_principal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.cli.commands.client_profile as command_module

    root = tmp_path / "client-support"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(root))
    active = {"username": "18717974771"}
    monkeypatch.setattr(
        FactorTesterClient,
        "current_principal",
        lambda self: {"username": active["username"]},
    )
    monkeypatch.setattr(
        FactorTesterClient,
        "factor_library_source_projection",
        lambda self, owner_ref: {
            "projection": {
                "principal": owner_ref,
                "owner_ref": owner_ref,
                "factors": [],
            },
            "projection_hash": owner_ref.zfill(64)[-64:],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_sync_profile",
        lambda _profile, *, manager_url="": {
            "status": "pending",
            "synced": False,
            "pending": True,
            "manager_url": manager_url,
        },
    )
    runner = CliRunner()
    base = [
        "client", "profile", "bootstrap",
        "--profile-id", "maxa",
        "--display-name", "MaxA",
        "--server-url", "http://127.0.0.1:8000",
        "--agent-id", "research-maxa",
    ]
    first = runner.invoke(cli, [*base, "--principal-ref", active["username"]])
    assert first.exit_code == 0, first.output
    before = (root / "profiles" / "maxa.json").read_bytes()

    active["username"] = "other-user"
    second = runner.invoke(cli, [*base, "--principal-ref", active["username"]])

    assert second.exit_code != 0
    assert "bound to another principal" in second.output
    assert (root / "profiles" / "maxa.json").read_bytes() == before


def test_local_agent_identity_resumes_without_provider_or_model_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "client-support"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(root))
    store = LocalProfileStore(root)
    store.save(new_local_profile(
        profile_id="agent-profile",
        display_name="Research Agent",
        server_url="http://127.0.0.1:8123",
        workspace_root=tmp_path / "workspace",
    ))
    runner = CliRunner()
    configured = runner.invoke(cli, [
        "client", "profile", "agent", "set", "agent-profile",
        "--agent-id", "planner-a",
        "--role", "planning",
        "--workspace-id", "workspace-1",
    ])
    assert configured.exit_code == 0, configured.output
    seen: list[tuple[str, dict]] = []

    def fake_resume(self, agent_id: str, **kwargs):
        seen.append((agent_id, kwargs))
        return {
            "schema_version": 1,
            "agent": {"agent_id": agent_id, "role": kwargs["role"]},
            "resume_ref": "sha256:stable",
            "packet_bytes": 180,
        }

    monkeypatch.setattr(FactorTesterClient, "resume_agent", fake_resume)
    first = runner.invoke(cli, [
        "agents", "flow", "resume-local", "agent-profile", "planner-a",
    ])
    second = runner.invoke(cli, [
        "agents", "flow", "resume-local", "agent-profile", "planner-a",
    ])

    assert first.exit_code == second.exit_code == 0
    assert json.loads(first.output) == json.loads(second.output)
    assert seen == [
        ("planner-a", {
            "role": "planning",
            "workspace_id": "workspace-1",
            "instance_id": "",
            "branch_id": "",
        }),
    ] * 2
    profile = store.load("agent-profile")
    serialized = json.dumps(profile).lower()
    assert "runtime_id" not in serialized
    assert "model_id" not in serialized
    assert "codex" not in serialized


def test_adapter_credentials_are_opaque_keychain_references(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = LocalProfileStore(root)
    store.save(new_local_profile(
        profile_id="human",
        display_name="Human",
        server_url="http://127.0.0.1:8123",
        workspace_root=tmp_path / "workspace",
    ))

    stored = store.upsert_adapter("human", {
        "adapter_id": "ai-trader",
        "enabled": True,
        "credential_ref": "keychain://ai4trade/token",
        "configuration_ref": "profile://ai-trader",
    })
    assert stored["adapters"][0]["credential_ref"].startswith("keychain://")
    with pytest.raises(ValueError, match="opaque"):
        store.upsert_adapter("human", {
            "adapter_id": "ai-trader",
            "enabled": True,
            "credential_ref": "secret-token",
            "configuration_ref": "",
        })


def test_adapter_profile_binding_exposes_only_opaque_references(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    config = tmp_path / "vibe.json"
    config.write_text('{"executable": "/tmp/vibe-trading"}')
    store = LocalProfileStore(root)
    store.save(new_local_profile(
        profile_id="human",
        display_name="Human",
        server_url="http://127.0.0.1:8123",
        workspace_root=tmp_path / "workspace",
    ))
    store.upsert_adapter("human", {
        "adapter_id": "vibe-trading",
        "enabled": True,
        "credential_ref": "keychain://com.gtht.client.adapters/human/vibe",
        "configuration_ref": config.as_uri(),
    })

    binding = adapter_binding(root, "human", "vibe-trading")

    assert binding["FACTORTESTER_ADAPTER_PROFILE_ID"] == "human"
    assert binding["FACTORTESTER_ADAPTER_CONFIGURATION_REF"] == str(config)
    assert binding["FACTORTESTER_ADAPTER_CREDENTIAL_REF"].startswith(
        "keychain://"
    )
    assert "password" not in json.dumps(binding).lower()


def test_profile_history_stores_only_compact_refs_and_deep_links(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = LocalProfileStore(root)
    store.save(new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8000",
        workspace_root=tmp_path / "workspace",
    ))
    record = {
        "record_id": "research-1",
        "title": "SgCCS review",
        "status": "ready",
        "scope": {"factor_families": ["SgCCS"]},
        "factor_family_versions": ["SgCCS@7"],
        "agent_id": "research-maxa",
        "created_at": 1.0,
        "updated_at": 2.0,
        "workspace_ref": "workspace:dd2322",
        "run_ref": "run:1",
        "graph_instance_ref": "instance:1",
        "graph_branch_ref": "branch:1",
        "checkpoint_ref": "checkpoint:1",
        "evidence_refs": ["evidence:1"],
        "timeline_refs": [{
            "link_id": "step-1",
            "kind": "trial_plan",
            "target_ref": "trial-plan:1",
            "section_ref": "section:method",
        }],
        "artifacts": [{
            "artifact_ref": "report:1",
            "format": "markdown",
            "status": "ready",
            "content_hash": "sha256:abc",
            "local_ref": (tmp_path / "report.md").as_uri(),
            "index_ref": (tmp_path / "REPORT.index.json").as_uri(),
            "section_refs": [{
                "link_id": "section-method",
                "kind": "evidence",
                "target_ref": "evidence:1",
                "section_ref": "section:method",
            }],
        }],
        "provenance": {
            "kind": "owned_legacy_research",
            "owner_ref": "default$MaxA@1",
        },
    }

    saved = store.upsert_research_record("maxa", record)

    assert saved["research_records"] == [{
        **record,
        "branch_bindings": [],
    }]
    serialized = json.dumps(saved)
    assert "report body" not in serialized
    assert "source_code" not in serialized


def test_ui_session_bridge_uses_stdin_and_verifies_principal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "cli-home"))
    monkeypatch.setattr(
        FactorTesterClient,
        "current_principal",
        lambda self: {"username": "18717974771"},
    )
    result = CliRunner().invoke(
        cli,
        [
            "client", "profile", "import-ui-session",
            "--server-url", "http://127.0.0.1:8000",
            "--principal-ref", "18717974771",
        ],
        input=json.dumps({"cookies": [{
            "name": "session",
            "value": "opaque-secret",
            "domain": "127.0.0.1",
            "path": "/",
            "secure": False,
        }]}),
    )

    assert result.exit_code == 0, result.output
    assert "opaque-secret" not in result.output
    assert json.loads(result.output)["verified"] is True
    restored = HttpSession("http://127.0.0.1:8000")
    assert [(cookie.name, cookie.value) for cookie in restored.cookie_jar] == [
        ("session", "opaque-secret")
    ]
