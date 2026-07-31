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
    assert created_value["member_count"] == 1
    assert "member_refs" not in created_value

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
    assert value["member_count"] == 1
    assert "member_refs" not in value
    assert value["target_ref"].startswith("factor-set:v1:profile-maxa:")

    members = CliRunner().invoke(client, [
        "profile", "factor-worktree", "factor-set", "members",
        "--target-ref", value["target_ref"], "--limit", "1", "--json",
    ])
    assert members.exit_code == 0, members.output
    page = json.loads(members.output)
    assert page["member_count"] == 1
    assert page["has_more"] is False
    assert page["related_references"][0]["target_ref"] == member_ref


def test_factor_set_introspection_and_guarded_update(
    tmp_path: Path, monkeypatch,
) -> None:
    root, source = _profile_with_factor_worktree(tmp_path)
    for module in (client_profile_factor_reference, client_profile_factor_set):
        monkeypatch.setattr(module, "load_profile_root", lambda _path: root)
    first_ref = _factor_ref(source, "SgCPS|N:20d")
    second_ref = _factor_ref(source, "SgCPS|N:40d")
    runner = CliRunner()
    created = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "create", "maxa",
        "--set-id", "momentum-column",
        "--title-zh", "动量因子集合",
        "--description-zh", "用于窗口参数比较",
        "--member-ref", first_ref,
        "--json",
    ])
    assert created.exit_code == 0, created.output
    created_value = json.loads(created.output)
    worktree = source.parents[1]
    _commit_all(worktree, "factor set v1")
    first = _factor_set_reference(runner, "momentum-column")

    listed = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "list", "maxa",
        "--query", "窗口", "--json",
    ])
    assert listed.exit_code == 0, listed.output
    listed_value = json.loads(listed.output)
    assert listed_value["count"] == 1
    assert listed_value["items"][0]["target_ref"] == first["target_ref"]

    shown = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "show", "maxa",
        "--set-id", "momentum-column", "--json",
    ])
    assert shown.exit_code == 0, shown.output
    shown_value = json.loads(shown.output)
    assert shown_value["member_count"] == 1
    assert "member_refs" not in shown_value
    assert shown_value["member_resolution"]["command"] == "members"

    member_file = tmp_path / "members.json"
    member_file.write_text(
        json.dumps([first_ref, second_ref]), encoding="utf-8",
    )
    stale = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "update", "maxa",
        "--set-id", "momentum-column",
        "--expected-member-hash", "sha256:" + ("0" * 64),
        "--title-zh", "动量因子集合",
        "--member-ref-file", str(member_file),
    ])
    assert stale.exit_code != 0
    assert "stale" in stale.output

    updated = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "update", "maxa",
        "--set-id", "momentum-column",
        "--expected-member-hash", created_value["member_hash"],
        "--title-zh", "动量因子集合",
        "--description-zh", "用于窗口参数比较",
        "--member-ref-file", str(member_file),
        "--json",
    ])
    assert updated.exit_code == 0, updated.output
    updated_value = json.loads(updated.output)
    assert updated_value["member_count"] == 2
    assert "member_refs" not in updated_value
    assert updated_value["next_actions"][2]["argv"][6] == "maxa"
    _commit_all(worktree, "factor set v2")
    second = _factor_set_reference(runner, "momentum-column")

    diff = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "diff",
        "--from-target-ref", first["target_ref"],
        "--to-target-ref", second["target_ref"],
        "--json",
    ])
    assert diff.exit_code == 0, diff.output
    diff_value = json.loads(diff.output)
    assert diff_value["changes"] == [{
        "change": "added", "target_ref": second_ref,
    }]
    assert diff_value["has_more"] is False


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


def _factor_ref(source: Path, identity: str) -> str:
    result = CliRunner().invoke(client, [
        "profile", "factor-worktree", "reference", "maxa",
        "--source-file", str(source),
        "--identity", identity,
        "--object-kind", "factor",
        "--json",
    ])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["target_ref"]


def _factor_set_reference(runner: CliRunner, set_id: str) -> dict:
    result = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "reference", "maxa",
        "--set-id", set_id, "--json",
    ])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _commit_all(repository: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(repository),
        "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "commit", "-qm", message,
    ], check=True)
