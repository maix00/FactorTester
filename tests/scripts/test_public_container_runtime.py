from __future__ import annotations

import subprocess

from server.manager import runtime as manager


def _git_failure(*_args, **_kwargs):
    raise subprocess.CalledProcessError(128, ["git"])


def test_immutable_fixed_service_does_not_require_git_metadata(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_IMMUTABLE_SOURCE", "1")
    monkeypatch.setenv("GTHT_SOURCE_REVISION", "a" * 40)
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_role="main",
        fixed_port=8000,
        fixed_branch="main",
    )
    monkeypatch.setattr(state, "_worktree_entries", _git_failure)

    assert [(item.branch, item.port, item.head) for item in state.worktrees()] == [
        ("main", 8000, "aaaaaaaa"),
    ]
    assert state._revision_for_path() == "a" * 40


def test_public_service_env_disables_debug_and_uses_image_revision(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_SERVICE_DEBUG", "0")
    monkeypatch.setenv("FACTORTESTER_HOT_RELOAD", "0")
    monkeypatch.setenv("GTHT_SOURCE_REVISION", "b" * 40)
    monkeypatch.setattr(manager.subprocess, "check_output", _git_failure)
    state = manager.ManagerState(tmp_path, "python")

    env, _, _ = state._service_env(tmp_path, 8000)

    assert env["FLASK_DEBUG"] == "0"
    assert env["FACTORTESTER_HOT_RELOAD"] == "0"
    assert env["GTHT_SOURCE_REVISION"] == "b" * 40
