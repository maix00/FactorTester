from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest
from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.release.factor_worktree import (
    CanonicalFactorRepoStore,
    apply_factor_worktree_binding,
    plan_factor_worktree_binding,
)
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile_lifecycle import ProfileLifecycle


OWNER = "factor-owner"


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        env={**os.environ, "FACTOR_WORKSPACE_SKIP_AUTOSYNC": "1"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _canonical(root: Path) -> Path:
    repo = root / "canonical"
    repo.mkdir()
    _git(repo, "init", "-b", "download")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")
    (repo / "custom_factors").mkdir()
    (repo / "custom_factors" / "Trend.py").write_text("value: int = 1\n")
    (repo / "tools").mkdir()
    (repo / "tools" / "__init__.pyi").write_text("value: int\n")
    (repo / "pyrightconfig.json").write_text(json.dumps({
        "include": ["custom_factors", "tools"],
        "reportMissingModuleSource": "none",
    }))
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    (repo / ".factor_workspace").mkdir()
    (repo / ".factor_workspace" / "manifest.json").write_text(json.dumps({
        "username": OWNER,
        "workspace_root": str(repo),
    }))
    return repo


def test_cli_create_and_lifecycle_receipts_are_idempotent(
    tmp_path: Path,
) -> None:
    client_root = tmp_path / "support"
    release_profile = tmp_path / "release.json"
    release_profile.write_text(json.dumps({
        "release": {"install_root": str(client_root)}
    }))
    workspace = tmp_path / "maxa"
    args = [
        "client", "profile", "create",
        "--profile-id", "maxa",
        "--display-name", "MaxA",
        "--server-url", "http://127.0.0.1:8000",
        "--workspace-root", str(workspace),
        "--agent-id", "research-a",
        "--role", "research",
        "--principal-ref", OWNER,
        "--release-profile", str(release_profile),
    ]
    runner = CliRunner()
    created = runner.invoke(cli, args)
    assert created.exit_code == 0, created.output
    receipt = json.loads(created.output)
    assert runner.invoke(cli, args).output == created.output
    assert {
        key for key in (
            "schema_version", "action", "status", "profile_id",
            "branch_retained", "commits_retained", "receipt_ref",
            "receipt_hash",
        ) if key not in receipt
    } == set()
    assert receipt["profile"]["agents"][0]["agent_id"] == "research-a"
    assert receipt["recommended_factor_worktree"]["branch"] == "agent/maxa"

    lifecycle = ProfileLifecycle(client_root)
    inactive = lifecycle.deactivate("maxa")
    assert lifecycle.deactivate("maxa") == inactive
    deleted = lifecycle.delete("maxa")
    assert lifecycle.delete("maxa") == deleted
    workspace.rmdir()
    purged = lifecycle.purge("maxa")
    assert lifecycle.purge("maxa") == purged
    assert purged["status"] == "purged"


def test_delete_refuses_dirty_worktree_and_retains_git_history(
    tmp_path: Path,
) -> None:
    client_root = tmp_path / "support"
    workspace = tmp_path / "maxa"
    lifecycle = ProfileLifecycle(client_root)
    lifecycle.create(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8000",
        workspace_root=workspace,
        principal_ref=OWNER,
    )
    repo = _canonical(tmp_path)
    CanonicalFactorRepoStore(client_root).register(repo, owner_ref=OWNER)
    receipt = apply_factor_worktree_binding(
        client_root, plan_factor_worktree_binding(client_root, "maxa")
    )
    worktree = Path(receipt["worktree_path"])
    (worktree / "custom_factors" / "Dirty.py").write_text("value = 1\n")
    lifecycle.deactivate("maxa")
    with pytest.raises(ValueError, match="uncommitted changes"):
        lifecycle.delete("maxa")
    assert worktree.is_dir()
    assert LocalProfileStore(client_root).load("maxa")["status"] == "inactive"
    assert not (client_root / "profiles/deleted/maxa.json").exists()

    (worktree / "custom_factors" / "Dirty.py").unlink()
    deleted = lifecycle.delete("maxa")
    assert deleted["branch_retained"] is True
    assert deleted["commits_retained"] is True
    assert not worktree.exists()
    assert _git(repo, "show-ref", "--verify", "refs/heads/agent/maxa")
    with pytest.raises(ValueError, match="not empty"):
        lifecycle.purge("maxa")
