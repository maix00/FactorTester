import json
from pathlib import Path
import subprocess

from click.testing import CliRunner

from tools.cli.commands import client_profile_factor_reference
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
