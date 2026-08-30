from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.release.factor_worktree import CanonicalFactorRepoStore
from tools.cli.release.profile_lifecycle import ProfileLifecycle
from tools.cli.release.user_layout import (
    default_user_factor_library,
    default_user_profile_root,
    user_layout_status,
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


def _fixture(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    repo = default_user_factor_library(OWNER)
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "download")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")
    (repo / ".factor_workspace").mkdir()
    (repo / ".factor_workspace/manifest.json").write_text(json.dumps({
        "username": OWNER,
        "workspace_root": str(repo),
    }))
    (repo / "Factor.py").write_text("value = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")

    client_root = tmp_path / "support"
    CanonicalFactorRepoStore(client_root).register(repo, owner_ref=OWNER)
    ProfileLifecycle(client_root).create(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        principal_ref=OWNER,
    )
    return repo, client_root


def test_unified_defaults_have_one_principal_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    user_root = tmp_path / "Documents/FactorTester/users" / OWNER
    assert default_user_factor_library(OWNER) == (
        user_root / "personal-workspace/factor-library"
    )
    assert default_user_profile_root(OWNER, "maxa") == (
        user_root / "profiles/maxa"
    )


def test_status_exposes_only_active_unified_layout(tmp_path, monkeypatch):
    repo, client_root = _fixture(tmp_path, monkeypatch)
    value = user_layout_status(client_root, OWNER)

    assert value["schema_version"] == 2
    assert value["factor_library"] == str(repo)
    assert value["profiles_root"].endswith(
        f"/users/{OWNER}/profiles"
    )
    assert value["profiles"][0]["workspace_root"].endswith(
        f"/users/{OWNER}/profiles/maxa"
    )
    serialized = json.dumps(value, sort_keys=True).lower()
    for obsolete in (
        "legacy", "quarantine", "migration", "source_layout",
        "target_layout", "personal-workspaces",
    ):
        assert obsolete not in serialized


def test_profile_cli_has_no_legacy_layout_commands(tmp_path, monkeypatch):
    _, client_root = _fixture(tmp_path, monkeypatch)
    release = tmp_path / "release.json"
    release.write_text(json.dumps({
        "release": {"install_root": str(client_root)}
    }))
    runner = CliRunner()

    help_result = runner.invoke(cli, ["client", "profile", "--help"])
    assert help_result.exit_code == 0, help_result.output
    for obsolete in ("personal-workspace", "init"):
        result = runner.invoke(cli, ["client", "profile", obsolete])
        assert result.exit_code == 2
        assert f"No such command '{obsolete}'" in result.output

    workspace_help = runner.invoke(
        cli, ["client", "profile", "workspace", "--help"]
    )
    assert workspace_help.exit_code == 0, workspace_help.output
    for command in ("bind", "list", "remove"):
        assert command in workspace_help.output

    layout_help = runner.invoke(
        cli, ["client", "profile", "user-layout", "--help"]
    )
    assert layout_help.exit_code == 0, layout_help.output
    assert "show" in layout_help.output
    assert "migration" not in layout_help.output
    assert "compact" not in layout_help.output

    for command in ("create", "bootstrap"):
        command_help = runner.invoke(
            cli, ["client", "profile", command, "--help"]
        )
        assert command_help.exit_code == 0, command_help.output
        assert "--workspace-root" not in command_help.output

    outside = tmp_path / "outside-factor-library"
    outside.mkdir()
    rejected = runner.invoke(cli, [
        "factor-library", "profile", "canonical-register",
        "--path", str(outside), "--owner-ref", OWNER,
        "--release-profile", str(release),
    ])
    assert rejected.exit_code != 0
    assert "must use the unified user layout" in rejected.output

    shown = runner.invoke(cli, [
        "client", "profile", "user-layout", "show",
        "--principal", OWNER,
        "--release-profile", str(release),
    ])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["factor_library"].endswith(
        "/personal-workspace/factor-library"
    )
