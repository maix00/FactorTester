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
    assert (target / "workspaces/shared-187-factor-library/.vscode").is_dir()
    assert verify_workspace_migration(client_root, "maxa")["valid"] is True

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
