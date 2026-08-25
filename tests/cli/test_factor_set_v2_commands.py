from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tools.cli.commands import client_profile_factor_set
from tools.cli.commands.client_release import client
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.factors.formula_identity import freeze_factor_identity


def test_factor_set_cli_uses_complete_formula_records_without_git(
    tmp_path: Path, monkeypatch,
) -> None:
    root = _profile_root(tmp_path)
    monkeypatch.setattr(
        client_profile_factor_set, "load_profile_root", lambda _path: root,
    )
    member = freeze_factor_identity(
        owner_ref="profile:maxa",
        family_alias="Momentum",
        factor_alias="Momentum|N:20d",
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={"N": "20d"},
    )
    runner = CliRunner()

    created = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "create", "maxa",
        "--set-id", "momentum", "--title-zh", "动量集合",
        "--member-record", json.dumps(member), "--json",
    ])
    assert created.exit_code == 0, created.output
    created_value = json.loads(created.output)
    assert created_value["target_ref"].startswith("factor-set:v2:")
    assert created_value["title_zh"] == "动量集合"
    assert created_value["member_count"] == 1
    assert created_value["next_actions"][0]["action"] == "sync_factor_set"

    reference = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "reference", "maxa",
        "--set-id", "momentum", "--json",
    ])
    assert reference.exit_code == 0, reference.output
    target_ref = json.loads(reference.output)["target_ref"]
    assert target_ref == created_value["target_ref"]

    members = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "members",
        "--target-ref", target_ref, "--json",
    ])
    assert members.exit_code == 0, members.output
    member_page = json.loads(members.output)
    assert member_page["related_references"][0]["label"] == "Momentum|N:20d"
    assert member_page["related_references"][0]["data"] == member

    descriptor = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "descriptor",
        "--target-ref", target_ref, "--json",
    ])
    assert descriptor.exit_code == 0, descriptor.output
    manifest = json.loads(descriptor.output)["manifest"]
    assert manifest["identity"]["members"] == [member]

    run_input = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "run-input",
        "--target-ref", target_ref, "--json",
    ])
    assert run_input.exit_code == 0, run_input.output
    assert json.loads(run_input.output)["transient_factor_sources"] == []


def _profile_root(tmp_path: Path) -> Path:
    worktree = tmp_path / "factor-worktree"
    worktree.mkdir()
    root = tmp_path / "client"
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
    )
    profile["factor_workspace_binding"] = {
        "binding_id": "factor-maxa",
        "canonical_repo_ref": "local-factor-git:maxa",
        "base_commit": "a" * 40,
        "branch": "research-maxa",
        "worktree_path": str(worktree),
        "research_root": str(tmp_path / "workspace" / "research"),
        "git_common_dir": str(worktree / ".git"),
        "owner_ref": "profile:maxa",
        "sync_policy": {
            "source_sync_enabled": False,
            "auto_push": False,
            "auto_merge": False,
        },
        "receipt_hash": "a" * 64,
        "receipt_ref": (tmp_path / "binding.json").resolve().as_uri(),
    }
    LocalProfileStore(root).save(profile)
    return root
