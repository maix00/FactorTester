from __future__ import annotations

import plistlib

from tools.cli.release import manager_process


def test_write_plist_runs_manager_from_publishing_worktree(tmp_path) -> None:
    source = tmp_path / "worktree"
    repository = tmp_path / "repository"
    script = source / "scripts/worktree_flask_manager.py"
    log = repository / ".workspace/flask-manager/logs/manager.log"
    plist = tmp_path / "manager.plist"

    manager_process._write_plist(
        plist,
        source=source,
        repository=repository,
        script=script,
        log=log,
        port=7998,
    )

    payload = plistlib.loads(plist.read_bytes())
    assert payload["Label"] == manager_process.LABEL
    assert payload["WorkingDirectory"] == str(source)
    assert payload["ProgramArguments"] == [
        manager_process.sys.executable,
        str(script),
        "--repo", str(repository),
        "--port", "7998",
        "--no-browser",
    ]
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is True
    assert plist.stat().st_mode & 0o777 == 0o600


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
