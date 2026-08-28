import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from server.manager.services.profile_agent_sandbox import (
    ProfileAgentSandbox,
    ProfileAgentSandboxError,
)


def test_sandbox_maps_only_profile_workspace_and_private_tmp(tmp_path: Path) -> None:
    workspace = tmp_path / "data" / "users" / "owner" / "profiles" / "self"
    workspace.mkdir(parents=True)
    sandbox = ProfileAgentSandbox(workspace_root=workspace, binary="true")

    command = sandbox.command(["codex", "app-server"])

    assert command[0].endswith("true")
    assert ["--bind", str(workspace), "/workspace"] == command[
        command.index("--bind") : command.index("--bind") + 3
    ]
    assert ["--tmpfs", "/tmp"] == command[
        command.index("--tmpfs") : command.index("--tmpfs") + 2
    ]
    assert "--proc" not in command
    assert str(workspace.parent) not in command
    assert command[-5:] == ["--chdir", "/workspace", "--", "codex", "app-server"]


def test_sandbox_rewrites_profile_environment_paths(tmp_path: Path) -> None:
    workspace = (tmp_path / "profile").resolve()
    workspace.mkdir()
    sandbox = ProfileAgentSandbox(workspace_root=workspace, binary="true")

    value = sandbox.environment(
        {
            "HOME": str(workspace / ".codex" / "home"),
            "CODEX_HOME": str(workspace / ".codex"),
            "PATH": "/usr/local/bin:/usr/bin",
        }
    )

    assert value["HOME"] == "/workspace/.codex/home"
    assert value["CODEX_HOME"] == "/workspace/.codex"
    assert value["PATH"] == "/usr/local/bin:/usr/bin"
    assert value["TMPDIR"] == "/tmp"


def test_sandbox_fails_closed_without_bubblewrap(tmp_path: Path) -> None:
    workspace = tmp_path / "profile"
    workspace.mkdir()
    sandbox = ProfileAgentSandbox(
        workspace_root=workspace,
        binary="definitely-missing-bubblewrap",
    )
    with pytest.raises(ProfileAgentSandboxError, match="bubblewrap is required"):
        sandbox.command(["codex"])


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or not shutil.which("bwrap"),
    reason="Bubblewrap integration requires Linux",
)
def test_sandbox_process_cannot_see_host_tmp_or_user_storage(tmp_path: Path) -> None:
    workspace = tmp_path / "profile"
    workspace.mkdir()
    (workspace / "owned.txt").write_text("owned", encoding="utf-8")
    host_tmp_marker = Path("/tmp/factortester-profile-agent-host-marker")
    host_tmp_marker.write_text("hidden", encoding="utf-8")
    try:
        command = ProfileAgentSandbox(workspace_root=workspace).command([
            "/bin/sh", "-c",
            (
                "test -f /workspace/owned.txt && "
                "test ! -e /tmp/factortester-profile-agent-host-marker && "
                "test ! -e /data/users"
            ),
        ])
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
    finally:
        host_tmp_marker.unlink(missing_ok=True)
