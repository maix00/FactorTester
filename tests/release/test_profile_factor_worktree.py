from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from server.manager.services.agent_workspace import ensure_server_profile_workspace
from server.manager.services.profile_factor_worktree import (
    ensure_server_profile_factor_worktree,
)
from tools.cli.release import factor_worktree
from tools.cli.release.factor_worktree import (
    CanonicalFactorRepoStore,
    apply_factor_worktree_binding,
    ensure_factor_worktree_binding,
    plan_factor_worktree_binding,
    rollback_factor_worktree_binding,
    verify_factor_worktree_binding,
)
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile

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
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        env={**os.environ, "FACTOR_WORKSPACE_SKIP_AUTOSYNC": "1"},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _canonical(
    root: Path,
    name: str = "canonical",
) -> tuple[Path, str]:
    repo = root / name
    repo.mkdir()
    _git(repo, "init", "-b", "download")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")
    (repo / "custom_factors").mkdir()
    factor = repo / "custom_factors" / "Trend.py"
    factor.write_text("value: int = 1\n")
    (repo / "tools").mkdir()
    (repo / "tools" / "__init__.pyi").write_text("value: int\n")
    (repo / "pyrightconfig.json").write_text(json.dumps({
        "include": ["custom_factors", "tools"],
        "reportMissingModuleSource": "none",
    }))
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / ".factor_workspace").mkdir()
    (repo / ".factor_workspace" / "manifest.json").write_text(json.dumps({
        "username": OWNER,
        "workspace_root": str(repo),
    }))
    # Real canonical checkouts may be dirty. These changes must be reported,
    # preserved, and excluded from profile worktrees based on recorded HEAD.
    factor.write_text("value: int = 2\n")
    (repo / "local-note.txt").write_text("do not inherit\n")
    return repo, base


def _profile(store: LocalProfileStore, root: Path, profile_id: str) -> None:
    store.save(new_local_profile(
        profile_id=profile_id,
        display_name=profile_id.upper(),
        server_url="http://127.0.0.1:8000",
        workspace_root=root / "profiles" / profile_id,
        principal_ref=OWNER,
    ))


def test_two_profiles_use_isolated_branches_over_shared_object_store(
    tmp_path: Path,
) -> None:
    repo, base = _canonical(tmp_path)
    client_root = tmp_path / "support"
    store = LocalProfileStore(client_root)
    for profile_id in ("maxa", "maxb", "maxc"):
        _profile(store, tmp_path, profile_id)
    settings = CanonicalFactorRepoStore(client_root).register(
        repo, owner_ref=OWNER
    )
    canonical_branch = _git(repo, "branch", "--show-current")
    canonical_status = _git(repo, "status", "--porcelain=v1")

    plan_a = plan_factor_worktree_binding(client_root, "maxa")
    plan_b = plan_factor_worktree_binding(client_root, "maxb")
    assert plan_a["branch"] == "agent/maxa"
    assert plan_b["branch"] == "agent/maxb"
    assert plan_a["base_commit"] == plan_b["base_commit"] == base
    assert plan_a["canonical_repo_ref"] == settings["canonical_repo_ref"]
    assert plan_a["canonical_checkout"]["dirty"] is True
    assert plan_a["canonical_checkout"]["status_count"] == 3
    assert plan_a["canonical_checkout"]["uncommitted_changes_inherited"] is False
    assert plan_a["capacity"]["objects_copied"] is False
    assert plan_a["sync_policy"] == {
        "source_sync_enabled": False,
        "auto_push": False,
        "auto_merge": False,
    }

    receipt_a = apply_factor_worktree_binding(client_root, plan_a)
    receipt_b = apply_factor_worktree_binding(client_root, plan_b)
    assert apply_factor_worktree_binding(client_root, plan_a) == receipt_a
    path_a = Path(receipt_a["worktree_path"])
    path_b = Path(receipt_b["worktree_path"])
    assert path_a != path_b
    assert _git(path_a, "rev-parse", "--git-common-dir") == (
        _git(path_b, "rev-parse", "--git-common-dir")
    )
    assert _git(path_a, "branch", "--show-current") == "agent/maxa"
    assert _git(path_b, "branch", "--show-current") == "agent/maxb"
    baseline_a = receipt_a["generated_baseline"]["baseline_commit"]
    baseline_b = receipt_b["generated_baseline"]["baseline_commit"]
    assert baseline_a == baseline_b
    assert baseline_a != base
    assert _git(path_a, "rev-parse", "HEAD") == baseline_a
    assert _git(path_b, "rev-parse", "HEAD") == baseline_b
    assert receipt_a["generated_baseline"]["changed_paths"] == [
        "pyrightconfig.json"
    ]
    assert receipt_a["generated_baseline"]["pyright"]["error_count"] == 0
    assert json.loads((path_a / "pyrightconfig.json").read_text())[
        "pythonVersion"
    ] == "3.10"
    assert (path_a / "custom_factors/Trend.py").read_text() == "value: int = 1\n"
    assert not (path_a / "local-note.txt").exists()
    assert not (path_a / ".git/objects").exists()
    assert Path(receipt_a["research_root"]) != path_a
    assert Path(receipt_b["research_root"]) != path_b
    assert verify_factor_worktree_binding(
        client_root, "maxa", run_pyright=True
    )["valid"] is True
    assert verify_factor_worktree_binding(
        client_root, "maxb", run_pyright=True
    )["valid"] is True
    assert _git(repo, "branch", "--show-current") == canonical_branch
    assert _git(repo, "status", "--porcelain=v1") == canonical_status

    (path_a / "custom_factors/OnlyMaxA.py").write_text("value: int = 3\n")
    assert not (path_b / "custom_factors/OnlyMaxA.py").exists()
    _git(path_a, "add", "custom_factors/OnlyMaxA.py")
    _git(path_a, "commit", "-m", "maxa only")
    maxa_commit = _git(path_a, "rev-parse", "HEAD")
    assert _git(path_b, "rev-parse", "HEAD") == baseline_b

    rolled_back = rollback_factor_worktree_binding(
        client_root, "maxa", receipt_a["binding_id"]
    )
    assert rolled_back["branch_retained"] is True
    assert rolled_back["commits_retained"] is True
    assert not path_a.exists()
    assert _git(repo, "show-ref", "--verify", "refs/heads/agent/maxa")
    assert _git(repo, "cat-file", "-t", maxa_commit) == "commit"
    assert path_b.is_dir()


def test_create_is_the_single_idempotent_lifecycle_entry(tmp_path: Path) -> None:
    repo, _ = _canonical(tmp_path)
    client_root = tmp_path / "support"
    store = LocalProfileStore(client_root)
    _profile(store, tmp_path, "maxa")
    CanonicalFactorRepoStore(client_root).register(repo, owner_ref=OWNER)

    created = ensure_factor_worktree_binding(client_root, "maxa")
    existing = ensure_factor_worktree_binding(client_root, "maxa")

    assert created["status"] == "created"
    assert created["created"] is True
    assert created["verification"]["valid"] is True
    assert existing["status"] == "existing"
    assert existing["created"] is False
    assert existing["binding"] == created["binding"]


def test_server_profile_adopts_portable_empty_factor_worktree_directory(
    tmp_path: Path,
) -> None:
    repo, base = _canonical(tmp_path)
    workspace = ensure_server_profile_workspace(
        tmp_path / "server-data",
        OWNER,
        "maxa",
    )
    target = workspace / "factor-worktree"
    assert target.is_dir() and not list(target.iterdir())

    first = ensure_server_profile_factor_worktree(
        OWNER,
        "maxa",
        workspace,
        workspace / ".factortester-client",
        canonical_root=repo,
    )
    def unexpected_sync(_principal: str) -> dict[str, object]:
        raise AssertionError("existing Profile binding must not resync canonical data")

    second = ensure_server_profile_factor_worktree(
        OWNER,
        "maxa",
        workspace,
        workspace / ".factortester-client",
        synchronize=unexpected_sync,
    )

    profile = LocalProfileStore(
        workspace / ".factortester-client",
    ).load("maxa")
    binding = profile["factor_workspace_binding"]
    assert first["created"] is True
    assert second["created"] is False
    assert first["verification"]["valid"] is True
    assert binding["branch"] == "agent/maxa"
    assert binding["base_commit"] == base
    assert Path(binding["worktree_path"]) == target
    assert (target / "custom_factors" / "Trend.py").read_text() == (
        "value: int = 1\n"
    )
    assert not (target / "local-note.txt").exists()


def test_collisions_and_post_plan_changes_fail_closed(tmp_path: Path) -> None:
    repo, _ = _canonical(tmp_path)
    client_root = tmp_path / "support"
    store = LocalProfileStore(client_root)
    for profile_id in ("maxa", "maxb"):
        _profile(store, tmp_path, profile_id)
    CanonicalFactorRepoStore(client_root).register(repo, owner_ref=OWNER)

    _git(repo, "branch", "agent/taken")
    recovered_branch = plan_factor_worktree_binding(
        client_root, "maxa", branch="agent/taken"
    )
    assert recovered_branch["ready"] is True
    assert recovered_branch["checks"]["branch_recovery"] == (
        "recoverable_same_base"
    )
    recovered = apply_factor_worktree_binding(client_root, recovered_branch)
    assert Path(recovered["worktree_path"]).is_dir()

    _git(repo, "switch", "-c", "agent/checked-out")
    branch_collision = plan_factor_worktree_binding(
        client_root, "maxb", branch="agent/checked-out"
    )
    assert branch_collision["ready"] is False
    assert branch_collision["checks"]["collisions"] == ["branch_exists"]
    assert branch_collision["checks"]["branch_recovery"] == (
        "manual_repair_required_unique_commits"
    )
    _git(repo, "switch", "download")

    occupied = tmp_path / "profiles" / "maxa" / "factor-worktrees" / "occupied"
    occupied.mkdir(parents=True)
    path_collision = plan_factor_worktree_binding(
        client_root, "maxa", worktree_path=occupied
    )
    assert path_collision["ready"] is False
    assert "target_exists" in path_collision["checks"]["collisions"]

    plan = plan_factor_worktree_binding(client_root, "maxb")
    (repo / "second-note.txt").write_text("changed after preview\n")
    with pytest.raises(ValueError, match="changed after plan"):
        apply_factor_worktree_binding(client_root, plan)
    assert not Path(plan["worktree_path"]).exists()
    assert subprocess.run(
        [
            "git", "-C", str(repo), "show-ref", "--verify", "--quiet",
            "refs/heads/agent/maxb",
        ],
        check=False,
    ).returncode != 0


def test_unchecked_profile_branch_behind_canonical_base_is_recovered(
    tmp_path: Path,
) -> None:
    repo, base = _canonical(tmp_path)
    client_root = tmp_path / "support"
    store = LocalProfileStore(client_root)
    _profile(store, tmp_path, "maxa")
    CanonicalFactorRepoStore(client_root).register(repo, owner_ref=OWNER)

    _git(repo, "branch", "agent/maxa", base)
    _git(repo, "restore", "custom_factors/Trend.py")
    (repo / "local-note.txt").unlink()
    (repo / "custom_factors/NewFromDatabase.py").write_text("value: int = 2\n")
    _git(repo, "add", "custom_factors/NewFromDatabase.py")
    _git(repo, "commit", "-m", "sync newer database sources")
    current = _git(repo, "rev-parse", "HEAD")

    plan = plan_factor_worktree_binding(client_root, "maxa")
    assert plan["ready"] is True
    assert plan["checks"]["branch_recovery"] == "recoverable_behind_base"

    receipt = apply_factor_worktree_binding(client_root, plan)
    target = Path(receipt["worktree_path"])
    assert receipt["base_commit"] == current
    assert (target / "custom_factors/NewFromDatabase.py").is_file()
    assert _git(
        repo,
        "merge-base",
        "--is-ancestor",
        current,
        _git(target, "rev-parse", "HEAD"),
    ) == ""
