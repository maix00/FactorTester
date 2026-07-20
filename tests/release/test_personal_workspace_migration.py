from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

from click.testing import CliRunner
import pytest

from tools.cli.app import cli
from tools.cli.release.factor_worktree import CanonicalFactorRepoStore
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.personal_workspace_migration import (
    apply_personal_workspace_migration,
    default_personal_factor_workspace,
    plan_personal_workspace_migration,
    rollback_personal_workspace_migration,
    verify_personal_workspace_migration,
)


OWNER = "18717974771"


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        env={**os.environ, "FACTOR_WORKSPACE_SKIP_AUTOSYNC": "1"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _fixture(
    tmp_path: Path,
) -> tuple[Path, Path, LocalProfileStore, Path]:
    source = tmp_path / "legacy" / "personal_workspace"
    source.mkdir(parents=True)
    _git(source, "init", "-b", "download")
    _git(source, "config", "user.email", "tests@example.invalid")
    _git(source, "config", "user.name", "Tests")
    (source / ".factor_workspace").mkdir()
    (source / ".factor_workspace/manifest.json").write_text(json.dumps({
        "username": OWNER,
        "workspace_root": str(source),
    }))
    (source / "Factor.py").write_text("value = 1\n")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "base")
    linked_root = tmp_path / "profiles"
    maxa = linked_root / "maxa/factor-worktrees/maxa"
    maxb = linked_root / "maxb/factor-worktrees/maxb"
    maxa.parent.mkdir(parents=True)
    maxb.parent.mkdir(parents=True)
    _git(source, "worktree", "add", "-b", "agent/maxa", str(maxa))
    _git(source, "worktree", "add", "-b", "agent/maxb", str(maxb))
    (source / "Factor.py").write_text("value = 2\n")
    (source / "untracked.txt").write_text("preserve main dirty\n")
    (maxa / "maxa-untracked.txt").write_text("preserve maxa dirty\n")

    client_root = tmp_path / "support"
    canonical = CanonicalFactorRepoStore(client_root).register(
        source, owner_ref=OWNER
    )
    store = LocalProfileStore(client_root)
    common = str((source / ".git").resolve())
    for profile_id, worktree in (("maxa", maxa), ("maxb", maxb)):
        profile = new_local_profile(
            profile_id=profile_id,
            display_name=profile_id.upper(),
            server_url="http://127.0.0.1:8000",
            workspace_root=linked_root / profile_id,
            principal_ref=OWNER,
        )
        receipt_path = (
            client_root / "profiles/factor-worktree-receipts"
            / profile_id / "historical.json"
        )
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text('{"historical":true}\n')
        profile["factor_workspace_binding"] = {
            "binding_id": f"factor-worktree-{profile_id}",
            "canonical_repo_ref": canonical["canonical_repo_ref"],
            "base_commit": _git(source, "rev-parse", "HEAD"),
            "branch": f"agent/{profile_id}",
            "worktree_path": str(worktree),
            "research_root": str(linked_root / profile_id / "research"),
            "git_common_dir": common,
            "owner_ref": OWNER,
            "sync_policy": {
                "source_sync_enabled": False,
                "auto_push": False,
                "auto_merge": False,
            },
            "receipt_hash": "a" * 64,
            "receipt_ref": receipt_path.resolve().as_uri(),
        }
        store.save(profile)
    return source, client_root, store, maxa


def test_default_personal_and_profile_layouts_are_parallel(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert default_personal_factor_workspace(OWNER) == (
        tmp_path
        / "Documents/FactorTester/personal-workspaces"
        / OWNER
        / "factor-library"
    )


def test_dirty_canonical_with_linked_worktrees_moves_repairs_and_rolls_back(
    tmp_path: Path,
) -> None:
    source, client_root, store, maxa = _fixture(tmp_path)
    target = tmp_path / "personal-workspaces" / OWNER / "factor-library"
    historical = Path(
        store.load("maxa")["factor_workspace_binding"]["receipt_ref"]
        .removeprefix("file://")
    )
    historical_hash = sha256(historical.read_bytes()).hexdigest()
    plan = plan_personal_workspace_migration(
        client_root, OWNER, target=target
    )
    assert plan["ready"] is True
    assert plan["transfer_mode"] == "atomic_move"
    assert plan["dirty_file_count"] == 2
    assert {item["branch"] for item in plan["worktrees"]} == {
        "download", "agent/maxa", "agent/maxb",
    }
    assert len(plan["linked_profiles"]) == 2

    receipt = apply_personal_workspace_migration(client_root, plan)
    assert receipt["preservation"] == {
        "branches": True,
        "commits": True,
        "uncommitted": True,
        "dirty_file_count": 2,
        "status_sha256": plan["status_sha256"],
    }
    assert not source.exists()
    assert (target / "untracked.txt").read_text() == "preserve main dirty\n"
    assert (maxa / "maxa-untracked.txt").read_text() == (
        "preserve maxa dirty\n"
    )
    assert Path(_git(maxa, "rev-parse", "--git-common-dir")).resolve() == (
        target / ".git"
    ).resolve()
    for profile_id in ("maxa", "maxb"):
        binding = store.load(profile_id)["factor_workspace_binding"]
        assert binding["canonical_repo_ref"] == (
            receipt["new_canonical_repo_ref"]
        )
        assert Path(binding["git_common_dir"]) == (target / ".git")
    assert sha256(historical.read_bytes()).hexdigest() == historical_hash
    verified = verify_personal_workspace_migration(
        client_root, receipt["migration_id"]
    )
    assert verified["valid"] is True

    rolled_back = rollback_personal_workspace_migration(
        client_root, receipt["migration_id"]
    )
    assert rolled_back["preserved_uncommitted"] is True
    assert source.is_dir()
    assert not target.exists()
    assert (source / "untracked.txt").read_text() == "preserve main dirty\n"
    assert Path(_git(maxa, "rev-parse", "--git-common-dir")).resolve() == (
        source / ".git"
    ).resolve()
    assert sha256(historical.read_bytes()).hexdigest() == historical_hash


def test_cli_plan_writes_and_prints_same_read_only_plan(
    tmp_path: Path,
) -> None:
    _, client_root, _, _ = _fixture(tmp_path)
    release_profile = tmp_path / "release.json"
    release_profile.write_text(json.dumps({
        "release": {"install_root": str(client_root)}
    }))
    output = tmp_path / "migration-plan.json"
    target = tmp_path / "target/factor-library"
    result = CliRunner().invoke(cli, [
        "client", "profile", "personal-workspace", "migration", "plan",
        "--principal", OWNER,
        "--target", str(target),
        "--output", str(output),
        "--release-profile", str(release_profile),
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == json.loads(output.read_text())
    assert not target.exists()


def test_failed_apply_restores_source_worktrees_settings_and_bindings(
    tmp_path: Path,
) -> None:
    source, client_root, store, maxa = _fixture(tmp_path)
    target = tmp_path / "target/factor-library"
    plan = plan_personal_workspace_migration(
        client_root, OWNER, target=target
    )
    old_ref = store.load("maxa")["factor_workspace_binding"][
        "canonical_repo_ref"
    ]

    def fail(name: str) -> None:
        if name == "after_profile_bindings":
            raise RuntimeError("simulated interruption")

    with pytest.raises(RuntimeError, match="simulated"):
        apply_personal_workspace_migration(
            client_root, plan, checkpoint=fail
        )
    assert source.is_dir()
    assert not target.exists()
    assert (source / "untracked.txt").read_text() == "preserve main dirty\n"
    assert _git(maxa, "status", "--porcelain")
    assert Path(_git(maxa, "rev-parse", "--git-common-dir")).resolve() == (
        source / ".git"
    ).resolve()
    assert CanonicalFactorRepoStore(client_root).load()["path"] == str(source)
    assert store.load("maxa")["factor_workspace_binding"][
        "canonical_repo_ref"
    ] == old_ref
