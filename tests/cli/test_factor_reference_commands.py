import json
from pathlib import Path
import subprocess

from click.testing import CliRunner

from tools.cli.commands import (
    client_profile_factor_reference,
    client_profile_factor_set,
)
from tools.cli.commands.client_release import client
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile


def test_profile_factor_reference_freezes_the_committed_blob(
    tmp_path: Path, monkeypatch,
) -> None:
    root, source = _profile_with_factor_worktree(tmp_path)
    monkeypatch.setattr(
        client_profile_factor_reference,
        "load_profile_root",
        lambda _path: root,
    )

    result = CliRunner().invoke(client, [
        "profile", "factor-worktree", "reference", "maxa",
        "--source-file", str(source),
        "--identity", "SgCPS|N:20d",
        "--object-kind", "factor",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["kind"] == "factor"
    assert value["object_kind"] == "factor"
    assert value["identity"] == "SgCPS|N:20d"
    assert value["target_ref"].startswith(
        "factor:v1:profile-maxa:"
    )
    assert "factortester://" not in result.output


def test_profile_factor_reference_rejects_uncommitted_source(
    tmp_path: Path, monkeypatch,
) -> None:
    root, source = _profile_with_factor_worktree(tmp_path)
    source.write_text("factor = 2\n", encoding="utf-8")
    monkeypatch.setattr(
        client_profile_factor_reference,
        "load_profile_root",
        lambda _path: root,
    )

    result = CliRunner().invoke(client, [
        "profile", "factor-worktree", "reference", "maxa",
        "--source-file", str(source),
        "--identity", "SgCPS",
        "--object-kind", "factor-family",
    ])

    assert result.exit_code != 0
    assert "commit it first" in result.output


def test_profile_factor_set_has_stable_id_and_frozen_member_manifest(
    tmp_path: Path, monkeypatch,
) -> None:
    root, source = _profile_with_factor_worktree(tmp_path)
    for module in (client_profile_factor_reference, client_profile_factor_set):
        monkeypatch.setattr(module, "load_profile_root", lambda _path: root)
    member_result = CliRunner().invoke(client, [
        "profile", "factor-worktree", "reference", "maxa",
        "--source-file", str(source),
        "--identity", "SgCPS|N:20d",
        "--object-kind", "factor",
        "--json",
    ])
    assert member_result.exit_code == 0, member_result.output
    member_ref = json.loads(member_result.output)["target_ref"]

    created = CliRunner().invoke(client, [
        "profile", "factor-worktree", "factor-set", "create", "maxa",
        "--set-id", "momentum-column-2025",
        "--title-zh", "2025年动量因子列",
        "--member-ref", member_ref,
        "--json",
    ])
    assert created.exit_code == 0, created.output
    created_value = json.loads(created.output)
    assert created_value["set_ref"] == (
        "factor-set:profile-maxa:momentum-column-2025"
    )
    assert created_value["member_refs"] == [member_ref]

    worktree = source.parents[1]
    subprocess.run(["git", "-C", str(worktree), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(worktree),
        "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "commit", "-qm", "factor set",
    ], check=True)
    frozen = CliRunner().invoke(client, [
        "profile", "factor-worktree", "factor-set", "reference", "maxa",
        "--set-id", "momentum-column-2025",
        "--json",
    ])
    assert frozen.exit_code == 0, frozen.output
    value = json.loads(frozen.output)
    assert value["object_kind"] == "factor-set"
    assert value["set_ref"] == created_value["set_ref"]
    assert value["member_refs"] == [member_ref]
    assert value["target_ref"].startswith("factor-set:v1:profile-maxa:")


def _profile_with_factor_worktree(
    tmp_path: Path,
) -> tuple[Path, Path]:
    worktree = tmp_path / "factor-worktree"
    source = worktree / "custom_factors" / "SgCPS.py"
    source.parent.mkdir(parents=True)
    source.write_text("factor = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(worktree)], check=True)
    subprocess.run(["git", "-C", str(worktree), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(worktree),
        "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "commit", "-qm", "factor",
    ], check=True)
    head = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    root = tmp_path / "client"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
    )
    profile["factor_workspace_binding"] = {
        "binding_id": "factor-maxa",
        "canonical_repo_ref": "local-factor-git:maxa",
        "base_commit": head,
        "branch": "research-maxa",
        "worktree_path": str(worktree),
        "research_root": str(tmp_path / "workspace" / "research"),
        "git_common_dir": str(worktree / ".git"),
        "owner_ref": "owner-1",
        "sync_policy": {
            "source_sync_enabled": False,
            "auto_push": False,
            "auto_merge": False,
        },
        "receipt_hash": "a" * 64,
        "receipt_ref": (tmp_path / "binding.json").resolve().as_uri(),
    }
    LocalProfileStore(root).save(profile)
    return root, source
