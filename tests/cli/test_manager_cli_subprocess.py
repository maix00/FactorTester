from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys


def _resolve_cli(name: str) -> list[str]:
    """Resolve an installed command, with a source fallback for development."""
    force_installed = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED") == "1"
    path = shutil.which(name)
    if path:
        return [path]
    if force_installed:
        raise RuntimeError(f"{name} is not installed")
    return [sys.executable, "-m", "tools.cli.manager_app"]


CLI = _resolve_cli("factortester-manager")


def _run(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        CLI + args,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_installed_or_source_cli_help() -> None:
    result = _run(["--help"])

    assert result.returncode == 0, result.stderr
    assert "server" in result.stdout
    assert "jobs" in result.stdout
    assert "restart-fleet" not in result.stdout


def test_group_help_is_discoverable() -> None:
    result = _run(["server", "--help"])

    assert result.returncode == 0, result.stderr
    assert "inspect" in result.stdout
    assert "access" in result.stdout


def test_configure_is_real_one_shot_command(tmp_path) -> None:
    config_path = tmp_path / "manager.json"
    env = dict(os.environ)
    env["FACTORTESTER_MANAGER_CONFIG"] = str(config_path)
    result = _run([
        "configure",
        "--host", "127.0.0.1",
        "--port", "7998",
        "--json",
    ], env=env)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["manager_url"] == "http://127.0.0.1:7998"
    assert json.loads(config_path.read_text(encoding="utf-8"))["base_url"] == (
        "http://127.0.0.1:7998"
    )
