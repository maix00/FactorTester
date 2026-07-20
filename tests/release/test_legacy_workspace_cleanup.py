from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from tools.cli.release.legacy_workspace_cleanup import (
    plan_legacy_workspace_cleanup,
    purge_legacy_workspaces,
)
from tests.release.test_personal_workspace_migration import (
    _fixture,
    _git,
)


def _clone(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", str(source), str(target)],
        check=True,
        capture_output=True,
    )
    _git(target, "config", "user.email", "tests@example.invalid")
    _git(target, "config", "user.name", "Tests")
    return target


def test_cleanup_plan_is_read_only_and_blocks_dirty_unique_or_referenced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, client_root, store, _ = _fixture(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    managed = home / "Documents/FactorTester/legacy"
    dirty = _clone(source, managed / "dirty")
    unique = _clone(source, managed / "unique")
    referenced = _clone(source, managed / "referenced")
    (dirty / "local.txt").write_text("uncommitted\n")
    (unique / "unique.txt").write_text("commit\n")
    _git(unique, "add", "unique.txt")
    _git(unique, "commit", "-m", "unique")
    profile = store.load("maxa")
    profile["workspace_root"] = str(referenced)
    store.save(profile)

    plan = plan_legacy_workspace_cleanup(
        client_root, [dirty, unique, referenced]
    )
    by_name = {
        Path(item["path"]).name: item for item in plan["entries"]
    }
    assert plan["default_action"] == "retain"
    assert plan["destructive_action_performed"] is False
    assert plan["safe_to_purge"] is False
    assert by_name["dirty"]["dirty_file_count"] == 1
    assert by_name["dirty"]["content_sha256"]
    assert by_name["unique"]["unique_commit_count"] == 1
    assert by_name["referenced"]["profile_refs"] == [{
        "profile_id": "maxa",
        "kind": "workspace_root",
    }]
    assert all(not item["safe_to_purge"] for item in plan["entries"])
    with pytest.raises(ValueError, match="safety gates"):
        purge_legacy_workspaces(client_root, plan)
    assert all(path.is_dir() for path in (dirty, unique, referenced))


def test_safe_purge_is_explicit_idempotent_recoverable_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, client_root, _, _ = _fixture(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    legacy = _clone(
        source,
        home / "Documents/FactorTester/legacy/maxa-unused",
    )
    plan = plan_legacy_workspace_cleanup(client_root, [legacy])
    assert plan["safe_to_purge"] is True
    assert plan["entries"][0]["unique_commit_count"] == 0
    assert plan["entries"][0]["profile_refs"] == []
    assert plan["entries"][0]["registered_worktree"] is False

    receipt = purge_legacy_workspaces(client_root, plan)
    assert receipt["status"] == "quarantined"
    assert receipt["branches_retained"] is True
    assert receipt["commits_retained"] is True
    assert receipt["content_retained"] is True
    assert not legacy.exists()
    quarantined = Path(receipt["mappings"][0]["quarantine"])
    assert quarantined.is_dir()
    assert (quarantined / "Factor.py").is_file()
    assert purge_legacy_workspaces(client_root, plan) == receipt
