from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

import pytest

from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.quarantine_compaction import (
    apply_quarantine_compaction,
    plan_quarantine_compaction,
    rollback_quarantine_compaction,
    verify_quarantine_compaction,
)
from tools.cli.release.user_layout_migration import (
    apply_user_layout_migration,
    plan_user_layout_migration,
)
from tests.release.test_personal_workspace_migration import (
    OWNER,
    _git,
)
from tests.release.test_user_layout_migration import _layout_fixture


def _clone(source: Path, target: Path) -> Path:
    subprocess.run(
        ["git", "clone", str(source), str(target)],
        check=True,
        capture_output=True,
    )
    _git(target, "config", "user.email", "tests@example.invalid")
    _git(target, "config", "user.name", "Tests")
    return target


def _compaction_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source, client_root, store, _, _ = _layout_fixture(
        tmp_path, monkeypatch
    )
    profile = store.load("maxa")
    profile_root = Path(profile["workspace_root"])
    workspace_root = profile_root / "workspaces"
    reachable_clean = _clone(source, workspace_root / "reachable-clean")
    reachable_dirty = _clone(source, workspace_root / "reachable-dirty")
    independent = workspace_root / "independent-history"
    independent.mkdir()
    _git(independent, "init", "-b", "independent")
    _git(independent, "config", "user.email", "tests@example.invalid")
    _git(independent, "config", "user.name", "Tests")
    (independent / "independent.txt").write_text("unique history\n")
    _git(independent, "add", "independent.txt")
    _git(independent, "commit", "-m", "independent")
    _git(independent, "branch", "archived-ref")
    _git(independent, "tag", "evidence-v1")
    _git(independent, "pack-refs", "--all")
    (independent / ".git/info/exclude").write_text(
        ".factor_workspace/\n"
    )
    (independent / ".factor_workspace").mkdir()
    (independent / ".factor_workspace/manifest.json").write_text(
        '{"ignored_but_required":true}\n'
    )

    (reachable_dirty / "Factor.py").write_text("staged\n")
    _git(reachable_dirty, "add", "Factor.py")
    (reachable_dirty / "Factor.py").write_text("worktree\n")
    untracked = reachable_dirty / "untracked.sh"
    untracked.write_text("#!/bin/sh\necho retained\n")
    untracked.chmod(0o755)
    profile["workspaces"].extend([
        {
            "workspace_id": "reachable-clean",
            "path": str(reachable_clean),
            "access_mode": "owner",
            "owner_ref": OWNER,
            "server_workspace_ref": "",
        },
        {
            "workspace_id": "reachable-dirty",
            "path": str(reachable_dirty),
            "access_mode": "owner",
            "owner_ref": OWNER,
            "server_workspace_ref": "",
        },
        {
            "workspace_id": "independent-history",
            "path": str(independent),
            "access_mode": "owner",
            "owner_ref": OWNER,
            "server_workspace_ref": "",
        },
    ])
    store.save(profile)
    layout_plan = plan_user_layout_migration(client_root, OWNER)
    layout_receipt = apply_user_layout_migration(client_root, layout_plan)
    return client_root, layout_receipt


def test_plan_classifies_four_quarantine_cases_and_rejects_unsafe_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, migration = _compaction_fixture(tmp_path, monkeypatch)
    plan = plan_quarantine_compaction(
        client_root, migration["migration_id"]
    )
    modes = [item["mode"] for item in plan["entries"]]
    assert modes.count("reachable_patch") == 2
    assert modes.count("independent_bundle") == 1
    assert modes.count("content_archive") == 2
    dirty = next(
        item for item in plan["entries"]
        if Path(item["path"]).name.endswith("reachable-dirty")
    )
    assert dirty["status_sha256"]
    assert dirty["untracked"][0]["mode"] == 0o755
    independent = next(
        item for item in plan["entries"]
        if item["mode"] == "independent_bundle"
    )
    assert independent["unique_commit_count"] > 0
    assert len(independent["refs"]) == 3
    assert independent["untracked"] == [{
        "path": ".factor_workspace/manifest.json",
        "kind": "file",
        "mode": 0o644,
        "sha256": independent["untracked"][0]["sha256"],
    }]
    assert plan["safe_to_compact"] is True

    non_git = next(
        Path(item["path"]) for item in plan["entries"]
        if item["mode"] == "content_archive"
    )
    (non_git / "unsafe-link").symlink_to(tmp_path / "outside")
    blocked = plan_quarantine_compaction(
        client_root, migration["migration_id"]
    )
    assert blocked["safe_to_compact"] is False
    assert any(
        item["unsafe_symlinks"] for item in blocked["entries"]
    )


def test_compact_verify_and_rollback_reconstruct_exact_working_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, migration = _compaction_fixture(tmp_path, monkeypatch)
    plan = plan_quarantine_compaction(
        client_root, migration["migration_id"]
    )
    receipt = apply_quarantine_compaction(client_root, plan)
    assert receipt["full_checkout_removed"] is True
    assert receipt["rebuild_verified"] is True
    assert receipt["before_bytes"] > receipt["after_bytes"]
    assert receipt["bytes_saved"] > 0
    for item in plan["entries"]:
        compact = Path(item["path"])
        assert (compact / "compact-manifest.json").is_file()
        assert not (compact / ".git").exists()
        if item["mode"] == "independent_bundle":
            assert (compact / "history.bundle").is_file()
        if item["git"]:
            assert (compact / "tracked-index.patch").is_file()
            assert (compact / "tracked-worktree.patch").is_file()
            assert (compact / "untracked.tar.gz").is_file()
    verified = verify_quarantine_compaction(
        client_root, plan["plan_hash"]
    )
    assert verified["valid"] is True

    rolled_back = rollback_quarantine_compaction(
        client_root, plan["plan_hash"]
    )
    assert rolled_back["content_verified"] is True
    for item in plan["entries"]:
        restored = Path(item["path"])
        assert restored.is_dir()
        if item["git"]:
            assert (restored / ".git").exists()
            assert _git(restored, "rev-parse", "HEAD") == item["head"]
            assert (
                __import__("hashlib").sha256(
                    subprocess.run(
                        [
                            "git", "-C", str(restored), "status",
                            "--porcelain=v1", "-z",
                        ],
                        capture_output=True,
                        check=True,
                    ).stdout
                ).hexdigest()
                == item["status_sha256"]
            )
    dirty = next(
        Path(item["path"]) for item in plan["entries"]
        if Path(item["path"]).name.endswith("reachable-dirty")
    )
    assert stat.S_IMODE((dirty / "untracked.sh").stat().st_mode) == 0o755
    assert LocalProfileStore(client_root).load("maxa")["workspaces"] == []


def test_compaction_failure_rebuilds_already_replaced_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, migration = _compaction_fixture(tmp_path, monkeypatch)
    plan = plan_quarantine_compaction(
        client_root, migration["migration_id"]
    )

    def fail(name: str) -> None:
        if name == "after_publish_0":
            raise RuntimeError("simulated interruption")

    with pytest.raises(RuntimeError, match="simulated"):
        apply_quarantine_compaction(
            client_root, plan, checkpoint=fail
        )
    for item in plan["entries"]:
        path = Path(item["path"])
        assert path.is_dir()
        assert not (path / "compact-manifest.json").exists()
        if item["git"]:
            assert (path / ".git").exists()
