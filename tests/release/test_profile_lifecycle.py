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
from tools.cli.release import factor_worktree
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile_lifecycle import ProfileLifecycle


OWNER = "factor-owner"


@pytest.fixture(autouse=True)
def _bundled_pyright(monkeypatch):
    monkeypatch.setattr(
        factor_worktree,
        "run_bundled_pyright",
        lambda _root: {
            "version": "1.1.411",
            "returncode": 0,
            "files_analyzed": 2,
            "error_count": 0,
            "warning_count": 0,
        },
    )


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


def test_cli_create_deactivate_and_legacy_purge_are_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client_root = tmp_path / "support"
    release_profile = tmp_path / "release.json"
    release_profile.write_text(json.dumps({
        "release": {"install_root": str(client_root)}
    }))
    workspace = (
        tmp_path / "Documents/FactorTester/users" / OWNER
        / "profiles/maxa"
    )
    args = [
        "client", "profile", "create",
        "--profile-id", "maxa",
        "--display-name", "MaxA",
        "--server-url", "http://127.0.0.1:8000",
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
    with pytest.raises(
        ValueError,
        match="authoritative server reference clearance",
    ):
        lifecycle.delete("maxa")
    assert LocalProfileStore(client_root).load("maxa")["status"] == "inactive"
    assert not (client_root / "profiles/deleted/maxa.json").exists()

    # Tombstones created by an older client remain locally purgeable.  New
    # deletions stay fail-closed until the server can prove reference safety.
    source = client_root / "profiles/maxa.json"
    tombstone = client_root / "profiles/deleted/maxa.json"
    tombstone.parent.mkdir(parents=True)
    os.replace(source, tombstone)
    workspace.rmdir()
    purged = lifecycle.purge("maxa")
    assert lifecycle.purge("maxa") == purged
    assert purged["status"] == "purged"


def test_delete_refuses_bound_profile_without_mutating_worktree_or_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client_root = tmp_path / "support"
    workspace = (
        tmp_path / "Documents/FactorTester/users" / OWNER
        / "profiles/maxa"
    )
    lifecycle = ProfileLifecycle(client_root)
    lifecycle.create(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8000",
        principal_ref=OWNER,
    )
    repo = _canonical(tmp_path)
    CanonicalFactorRepoStore(client_root).register(repo, owner_ref=OWNER)
    receipt = apply_factor_worktree_binding(
        client_root, plan_factor_worktree_binding(client_root, "maxa")
    )
    worktree = Path(receipt["worktree_path"])
    lifecycle.deactivate("maxa")
    with pytest.raises(
        ValueError,
        match="authoritative server reference clearance",
    ):
        lifecycle.delete("maxa")
    assert worktree.is_dir()
    assert LocalProfileStore(client_root).load("maxa")["status"] == "inactive"
    assert not (client_root / "profiles/deleted/maxa.json").exists()
    assert _git(repo, "show-ref", "--verify", "refs/heads/agent/maxa")


def test_delete_refuses_unbound_profile_when_server_references_are_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client_root = tmp_path / "support"
    lifecycle = ProfileLifecycle(client_root)
    lifecycle.create(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8000",
        principal_ref=OWNER,
    )
    lifecycle.deactivate("maxa")
    before = LocalProfileStore(client_root).load("maxa")

    with pytest.raises(
        ValueError,
        match="authoritative server reference clearance",
    ):
        lifecycle.delete("maxa")

    assert LocalProfileStore(client_root).load("maxa") == before
    assert not (client_root / "profiles/deleted/maxa.json").exists()
    assert not (
        client_root / "profiles/lifecycle-receipts/maxa/delete.json"
    ).exists()
