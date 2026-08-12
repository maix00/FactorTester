from __future__ import annotations

import plistlib

import pytest

from tools.cli.release import manager_process


def test_write_plist_runs_manager_from_publishing_worktree(tmp_path) -> None:
    source = tmp_path / "worktree"
    repository = tmp_path / "repository"
    entrypoint = source / "server/manager/app.py"
    log = tmp_path / "Library/Logs/FactorTester/manager.log"
    plist = tmp_path / "manager.plist"
    data_root = tmp_path / "FactorTester"

    manager_process._write_plist(
        plist,
        source=source,
        repository=repository,
        entrypoint=entrypoint,
        log=log,
        port=7998,
        data_root=data_root,
        python_executable=tmp_path / "server-runtime/bin/python",
    )

    payload = plistlib.loads(plist.read_bytes())
    assert payload["Label"] == manager_process.LABEL
    assert payload["WorkingDirectory"] == str(source)
    assert payload["ProgramArguments"] == [
        str(tmp_path / "server-runtime/bin/python"),
        "-m", "server.manager.app",
        "--repo", str(repository),
        "--port", "7998",
        "--python", str(tmp_path / "server-runtime/bin/python"),
        "--data-root", str(data_root),
        "--no-browser",
    ]
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is True
    assert plist.stat().st_mode & 0o777 == 0o600


def test_resolve_python_reuses_validated_launch_agent_runtime(
    monkeypatch, tmp_path,
) -> None:
    plist = tmp_path / "manager.plist"
    server_python = tmp_path / "server-runtime/bin/python"
    plist.write_bytes(plistlib.dumps({
        "ProgramArguments": [
            str(server_python), "manager.py", "--python", str(server_python),
        ],
    }))
    checked: list[object] = []
    monkeypatch.setattr(
        manager_process,
        "_is_python_interpreter",
        lambda candidate: checked.append(candidate) or candidate == server_python,
    )
    monkeypatch.setattr(manager_process.sys, "executable", "/app/factortester")

    assert manager_process._resolve_python_executable(plist) == server_python
    assert checked == [server_python]


def test_resolve_python_rejects_frozen_cli_without_server_runtime(
    monkeypatch, tmp_path,
) -> None:
    plist = tmp_path / "manager.plist"
    plist.write_bytes(plistlib.dumps({
        "ProgramArguments": ["/app/factortester", "manager.py"],
    }))
    monkeypatch.setattr(
        manager_process, "_is_python_interpreter", lambda _candidate: False,
    )
    monkeypatch.setattr(manager_process.sys, "executable", "/app/factortester")

    with pytest.raises(RuntimeError, match="server Python runtime"):
        manager_process._resolve_python_executable(plist)


def test_unload_launch_agent_waits_until_service_is_absent(
    monkeypatch, tmp_path,
) -> None:
    calls: list[list[str]] = []
    states = iter([True, True, False])

    class Result:
        returncode = 0

    monkeypatch.setattr(
        manager_process.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command) or Result(),
    )
    monkeypatch.setattr(
        manager_process,
        "_launch_agent_loaded",
        lambda _service: next(states),
    )
    monkeypatch.setattr(manager_process.time, "sleep", lambda _seconds: None)

    manager_process._unload_launch_agent(
        domain="gui/501",
        service="gui/501/com.gtht.factortester.manager",
        plist=tmp_path / "manager.plist",
    )

    assert calls[:3] == [
        ["launchctl", "disable", "gui/501/com.gtht.factortester.manager"],
        ["launchctl", "bootout", "gui/501/com.gtht.factortester.manager"],
        ["launchctl", "bootout", "gui/501", str(tmp_path / "manager.plist")],
    ]


def test_repository_root_resolves_linked_worktree_common_dir(
    monkeypatch, tmp_path,
) -> None:
    source = tmp_path / "worktree"
    common = tmp_path / "repository/.git"
    monkeypatch.setattr(
        manager_process.subprocess,
        "check_output",
        lambda *_args, **_kwargs: str(common) + "\n",
    )

    assert manager_process._repository_root(source) == common.parent


def test_stop_unmanaged_listener_rejects_unknown_process(
    monkeypatch,
) -> None:
    class Result:
        stdout = "42\n"

    monkeypatch.setattr(
        manager_process.subprocess,
        "run",
        lambda *_args, **_kwargs: Result(),
    )
    monkeypatch.setattr(
        manager_process.subprocess,
        "check_output",
        lambda *_args, **_kwargs: "/usr/bin/python unrelated.py\n",
    )

    try:
        manager_process._stop_unmanaged_listener(7998)
    except RuntimeError as exc:
        assert "unknown process" in str(exc)
    else:
        raise AssertionError("unknown listener must not be terminated")
