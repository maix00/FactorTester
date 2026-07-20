from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.release.factor_worktree import CanonicalFactorRepoStore
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile_lifecycle import ProfileLifecycle
from tools.cli.release.user_layout_migration import (
    apply_user_layout_migration,
    default_user_factor_library,
    default_user_profile_root,
    plan_user_layout_migration,
    rollback_user_layout_migration,
    verify_user_layout_migration,
)
from tests.release.test_personal_workspace_migration import (
    OWNER,
    _fixture,
    _git,
)


def _layout_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source, client_root, store, maxa_worktree = _fixture(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    for profile_id in ("maxa", "maxb"):
        profile = store.load(profile_id)
        profile["agents"] = [{
            "agent_id": f"research-{profile_id}",
            "role": "research",
            "scope": {"instance_id": "i-1", "branch_id": "b-1"},
            "status": "ready",
            "next_action": "Continue.",
        }]
        root = Path(profile["workspace_root"])
        (root / "research").mkdir()
        (root / "research" / "report.md").write_text(profile_id)
        (root / "local-data").mkdir()
        (root / "local-data" / "data.bin").write_bytes(
            profile_id.encode()
        )
        if profile_id == "maxa":
            legacy = root / "workspaces" / "legacy-maxa"
            legacy.mkdir(parents=True)
            (legacy / "old.txt").write_text("legacy")
            unsafe = root / ".maxa.unsafe-backup"
            unsafe.mkdir()
            (unsafe / "backup.txt").write_text("backup")
            profile["workspaces"] = [{
                "workspace_id": "legacy-maxa",
                "path": str(legacy),
                "access_mode": "owner",
                "owner_ref": OWNER,
                "server_workspace_ref": "",
            }]
        store.save(profile)
        store.claim_agent(profile_id, f"research-{profile_id}")
    historical = client_root / "profiles/factor-worktree-receipts/maxa/historical.json"
    return source, client_root, store, maxa_worktree, historical


def test_principal_defaults_and_create_without_explicit_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert default_user_factor_library(OWNER) == (
        tmp_path / "Documents/FactorTester/users" / OWNER
        / "personal-workspace/factor-library"
    )
    expected = (
        tmp_path / "Documents/FactorTester/users" / OWNER
        / "profiles/maxa"
    )
    assert default_user_profile_root(OWNER, "maxa") == expected
    lifecycle = ProfileLifecycle(tmp_path / "support")
    receipt = lifecycle.create(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8000",
        workspace_root=None,
        principal_ref=OWNER,
    )
    assert receipt["profile"]["workspace_root"] == str(expected)
    assert receipt["recommended_factor_worktree"]["worktree_path"] == str(
        expected / "factor-worktree"
    )


def test_unified_layout_preserves_and_repairs_everything_then_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, client_root, store, old_maxa_worktree, historical = (
        _layout_fixture(tmp_path, monkeypatch)
    )
    historical_hash = sha256(historical.read_bytes()).hexdigest()
    plan = plan_user_layout_migration(client_root, OWNER)
    assert plan["operation"] == "principal_user_layout_migration"
    assert plan["ready"] is True
    assert plan["canonical"]["dirty_file_count"] == 2
    assert len(plan["profiles"]) == 2
    assert {Path(item["new_path"]).name for item in plan["worktrees"]} == {
        "factor-library", "factor-worktree",
    }
    assert len(plan["legacy_quarantine"]) == 2
    assert all(item["content_sha256"] for item in plan["legacy_quarantine"])

    receipt = apply_user_layout_migration(client_root, plan)
    target_canonical = Path(plan["canonical"]["target"])
    maxa_root = default_user_profile_root(OWNER, "maxa")
    maxa_worktree = maxa_root / "factor-worktree"
    assert not source.exists()
    assert target_canonical.is_dir()
    assert not old_maxa_worktree.exists()
    assert maxa_worktree.is_dir()
    assert (maxa_root / "research/report.md").read_text() == "maxa"
    assert (maxa_root / "local-data/data.bin").read_bytes() == b"maxa"
    assert (target_canonical / "untracked.txt").is_file()
    assert (maxa_worktree / "maxa-untracked.txt").is_file()
    assert Path(_git(
        maxa_worktree, "rev-parse", "--git-common-dir"
    )).resolve() == (target_canonical / ".git").resolve()
    profile = store.load("maxa")
    assert profile["workspace_root"] == str(maxa_root)
    assert profile["workspaces"] == []
    assert profile["factor_workspace_binding"]["worktree_path"] == str(
        maxa_worktree
    )
    assert profile["factor_workspace_binding"]["research_root"] == str(
        maxa_root / "research"
    )
    assert _git(
        maxa_worktree,
        "config",
        "--worktree",
        "--get",
        "core.hooksPath",
    ) == str(maxa_worktree / ".factortester/hooks-disabled")
    assert _git(
        maxa_worktree,
        "config",
        "--worktree",
        "--get",
        "core.excludesFile",
    ) == str(maxa_root / "research/factor-worktree.gitignore")
    claim = store.claim_agent("maxa", "research-maxa")
    assert claim["recommended_cwd"] == str(maxa_worktree)
    assert sha256(historical.read_bytes()).hexdigest() == historical_hash
    assert verify_user_layout_migration(
        client_root, receipt["migration_id"]
    )["valid"] is True

    rolled_back = rollback_user_layout_migration(
        client_root, receipt["migration_id"]
    )
    assert rolled_back["uncommitted_retained"] is True
    assert source.is_dir()
    assert old_maxa_worktree.is_dir()
    assert not target_canonical.exists()
    assert Path(_git(
        old_maxa_worktree, "rev-parse", "--git-common-dir"
    )).resolve() == (source / ".git").resolve()
    old_profile = store.load("maxa")
    assert old_profile["workspace_root"].endswith("/profiles/maxa")
    assert old_profile["workspaces"]
    assert sha256(historical.read_bytes()).hexdigest() == historical_hash


def test_unified_layout_failure_restores_all_paths_and_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, client_root, store, old_maxa_worktree, _ = _layout_fixture(
        tmp_path, monkeypatch
    )
    plan = plan_user_layout_migration(client_root, OWNER)
    old_profile = store.load("maxa")
    old_settings = CanonicalFactorRepoStore(client_root).load()

    def fail(name: str) -> None:
        if name == "after_metadata":
            raise RuntimeError("simulated failure")

    with pytest.raises(RuntimeError, match="simulated"):
        apply_user_layout_migration(
            client_root, plan, checkpoint=fail
        )
    assert source.is_dir()
    assert old_maxa_worktree.is_dir()
    assert store.load("maxa") == old_profile
    assert CanonicalFactorRepoStore(client_root).load() == old_settings
    assert (source / "untracked.txt").is_file()
    assert (old_maxa_worktree / "maxa-untracked.txt").is_file()


def test_user_layout_cli_plan_writes_and_prints_same_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client_root, _, _, _ = _layout_fixture(tmp_path, monkeypatch)
    release = tmp_path / "release.json"
    release.write_text(json.dumps({
        "release": {"install_root": str(client_root)}
    }))
    output = tmp_path / "plan.json"
    result = CliRunner().invoke(cli, [
        "client", "profile", "user-layout", "migration", "plan",
        "--principal", OWNER,
        "--output", str(output),
        "--release-profile", str(release),
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == json.loads(output.read_text())
