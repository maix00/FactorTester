from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.local_profile import validate_local_profile


def test_local_profile_is_strict_private_and_version_independent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = LocalProfileStore(root)
    profile = new_local_profile(
        profile_id="research-a",
        display_name="Research A",
        server_url="http://127.0.0.1:8123/",
        workspace_root=tmp_path / "workspace",
    )
    stored = store.save(profile)

    assert stored["server"]["base_url"] == "http://127.0.0.1:8123"
    assert store.load("research-a") == stored
    path = root / "profiles" / "research-a.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert not (root / "current.json").exists()
    assert not {"password", "token", "email"}.intersection(stored)

    with pytest.raises(ValueError, match="fields"):
        validate_local_profile({**stored, "token": "must-not-be-stored"})


def test_client_cli_exposes_generic_profile_and_adapter_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "client-support"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(root))
    runner = CliRunner()

    result = runner.invoke(cli, [
        "client", "profile", "init",
        "--profile-id", "research-a",
        "--display-name", "Research A",
        "--server-url", "http://127.0.0.1:8123",
        "--workspace-root", str(tmp_path / "workspace"),
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["profile_id"] == "research-a"
    assert runner.invoke(cli, ["client", "profile", "list"]).exit_code == 0
    adapters = runner.invoke(cli, ["client", "adapter", "list"])
    assert adapters.exit_code == 0
    assert json.loads(adapters.output) == []
