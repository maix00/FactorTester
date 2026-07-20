from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.workspace_migration import (
    apply_workspace_migration,
    plan_workspace_migration,
    rollback_workspace_migration,
    verify_workspace_migration,
)


def _workspace(root: Path, owner: str, factor: str) -> Path:
    (root / ".factor_workspace").mkdir(parents=True)
    (root / ".factor_workspace/manifest.json").write_text(
        json.dumps({"username": owner, "workspace_root": str(root)})
    )
    (root / ".git").mkdir()
    (root / ".git/hooks").mkdir()
    (root / ".git/hooks/post-commit").write_text(
        "#!/bin/sh\n/private/server/sync\n"
    )
    (root / ".vscode").mkdir()
    (root / "pyrightconfig.json").write_text("{}")
    (root / "custom_factors").mkdir()
    (root / "custom_factors" / factor).write_text("class Factor: ...\n")
    return root


def _profile(client_root: Path, old_root: Path) -> LocalProfileStore:
    store = LocalProfileStore(client_root)
    store.save(new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8150",
        workspace_root=old_root,
    ))
    return store


def test_workspace_migration_preserves_distinct_owners_and_rolls_back(
    tmp_path: Path,
) -> None:
    client_root = tmp_path / "support"
    old_root = tmp_path / "old"
    store = _profile(client_root, old_root)
    maxa = _workspace(tmp_path / "maxa-source", "default$MaxA@1", "A.py")
    shared = _workspace(tmp_path / "shared-source", "18717974771", "B.py")
    target = tmp_path / "Documents/FactorTester/profiles/maxa"
    plan = plan_workspace_migration("maxa", target, [
        {
            "workspace_id": "maxa-factor-library",
            "source": str(maxa),
            "access_mode": "owner",
            "server_workspace_ref": "default$MaxA@1",
        },
        {
            "workspace_id": "shared-187-factor-library",
            "source": str(shared),
            "access_mode": "granted",
            "server_workspace_ref": "",
        },
    ])

    receipt = apply_workspace_migration(client_root, plan)
    profile = store.load("maxa")
    assert profile["workspace_root"] == str(target)
    assert {
        item["owner_ref"] for item in profile["workspaces"]
    } == {"default$MaxA@1", "18717974771"}
    assert maxa.is_dir() and shared.is_dir()
    assert (target / "workspaces/maxa-factor-library/.git").is_dir()
    assert not (
        target / "workspaces/maxa-factor-library/.git/hooks/post-commit"
    ).exists()
    assert (target / "workspaces/shared-187-factor-library/.vscode").is_dir()
    assert verify_workspace_migration(client_root, "maxa")["valid"] is True
    migrated_manifest = json.loads((
        target
        / "workspaces/maxa-factor-library/.factor_workspace/manifest.json"
    ).read_text())
    assert migrated_manifest["workspace_root"] == str(
        target / "workspaces/maxa-factor-library"
    )
    assert receipt["workspaces"][0]["removed_hooks"] == ["post-commit"]

    rolled_back = rollback_workspace_migration(
        client_root, "maxa", receipt["migration_id"]
    )
    assert rolled_back["status"] == "rolled_back"
    assert store.load("maxa")["workspace_root"] == str(old_root.resolve())
    assert target.is_dir()


def test_workspace_plan_cli_is_dry_run_and_hash_bound(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client_root = tmp_path / "support"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(client_root))
    source = _workspace(tmp_path / "source", "default$MaxA@1", "A.py")
    target = tmp_path / "target"
    output = tmp_path / "plan.json"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "client", "profile", "workspace", "plan", "maxa",
        "--workspace", "maxa-factor-library", str(source), "owner",
        "default$MaxA@1",
        "--target-root", str(target),
        "--output", str(output),
    ])

    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["capacity_ok"] is True
    assert plan["workspaces"][0]["inventory"]["owner_ref"] == "default$MaxA@1"
    assert output.is_file()
    assert not target.exists()


def test_workspace_apply_fails_if_source_changes_after_plan(
    tmp_path: Path,
) -> None:
    client_root = tmp_path / "support"
    _profile(client_root, tmp_path / "old")
    source = _workspace(tmp_path / "source", "default$MaxA@1", "A.py")
    target = tmp_path / "target"
    plan = plan_workspace_migration("maxa", target, [{
        "workspace_id": "maxa-factor-library",
        "source": str(source),
        "access_mode": "owner",
        "server_workspace_ref": "default$MaxA@1",
    }])
    (source / "custom_factors/A.py").write_text("changed\n")

    try:
        apply_workspace_migration(client_root, plan)
    except ValueError as error:
        assert "changed after plan" in str(error)
    else:
        raise AssertionError("migration should fail closed")

    assert not target.exists()
    assert LocalProfileStore(client_root).load("maxa")["workspaces"] == []


def test_workspace_plan_rejects_symlink_outside_source(
    tmp_path: Path,
) -> None:
    source = _workspace(tmp_path / "source", "default$MaxA@1", "A.py")
    (source / "outside").symlink_to(tmp_path)

    try:
        plan_workspace_migration("maxa", tmp_path / "target", [{
            "workspace_id": "maxa-factor-library",
            "source": str(source),
            "access_mode": "owner",
            "server_workspace_ref": "default$MaxA@1",
        }])
    except ValueError as error:
        assert "symlinks outside" in str(error)
    else:
        raise AssertionError("unsafe symlink should be rejected")


def test_workspace_rollback_refuses_to_overwrite_newer_profile_pointer(
    tmp_path: Path,
) -> None:
    client_root = tmp_path / "support"
    store = _profile(client_root, tmp_path / "old")
    source = _workspace(tmp_path / "source", "default$MaxA@1", "A.py")
    plan = plan_workspace_migration("maxa", tmp_path / "target", [{
        "workspace_id": "maxa-factor-library",
        "source": str(source),
        "access_mode": "owner",
        "server_workspace_ref": "default$MaxA@1",
    }])
    receipt = apply_workspace_migration(client_root, plan)
    profile = store.load("maxa")
    profile["workspace_root"] = str(tmp_path / "newer")
    store.save(profile)

    try:
        rollback_workspace_migration(
            client_root, "maxa", receipt["migration_id"]
        )
    except ValueError as error:
        assert "no longer points" in str(error)
    else:
        raise AssertionError("stale rollback should be refused")
