from __future__ import annotations

from pathlib import Path

import pytest

from scripts import worktree_flask_manager as manager


class _Process:
    next_pid = 100

    def __init__(self, command):
        type(self).next_pid += 1
        self.pid = type(self).next_pid
        self.command = list(command)
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0


def test_manager_starts_bundle_and_api_restart_preserves_daemon(tmp_path, monkeypatch) -> None:
    (tmp_path / "start_server.py").write_text("", encoding="ascii")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "research_job_daemon.py").write_text("", encoding="ascii")
    created = []

    def fake_popen(command, **kwargs):
        process = _Process(command)
        created.append((process, kwargs))
        return process

    monkeypatch.setattr(manager.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(manager.subprocess, "check_output", lambda *args, **kwargs: "abc123\n")
    monkeypatch.setattr(manager, "port_in_use", lambda port: False)
    monkeypatch.setattr(manager.ManagerState, "_terminate", staticmethod(lambda process: setattr(process, "returncode", 0)))
    state = manager.ManagerState(tmp_path, "python")

    state.start(tmp_path, 8135)
    bundle = state.processes[state.key(tmp_path)]
    daemon_pid = bundle.daemon.pid
    old_api_pid = bundle.api.pid
    state.restart_api(tmp_path, 8135)

    assert bundle.daemon.pid == daemon_pid
    assert bundle.daemon.poll() is None
    assert bundle.api.pid != old_api_pid
    assert created[0][0].command[1] == "scripts/research_job_daemon.py"
    assert created[1][1]["env"]["GTHT_DEPLOYMENT_ID"].endswith("-8135")
    assert created[1][1]["env"]["GTHT_JOB_DAEMON_SOCKET"] == str(bundle.socket_path)
    assert created[1][1]["env"]["FLASK_SECRET_KEY"]
    assert created[1][1]["env"]["FLASK_SECRET_KEY"] == created[2][1]["env"]["FLASK_SECRET_KEY"]
    assert (tmp_path / ".workspace" / "flask-manager" / "flask-secret.key").stat().st_mode & 0o777 == 0o600


def test_paused_step_job_blocks_drained_bundle_restart(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    daemon = _Process(["daemon"])
    api = _Process(["api"])
    bundle = manager.ServiceBundle(
        api=api,
        daemon=daemon,
        socket_path=tmp_path / "jobs.sock",
        deployment_id="test",
    )
    state.processes[state.key(tmp_path)] = bundle
    actions = []

    def request(current, action):
        actions.append(action)
        if action == "drain":
            return {"paused_jobs": ["step-1"], "active_planners": 0, "active_executors": 1}
        return {"paused_jobs": [], "active_planners": 0, "active_executors": 0}

    monkeypatch.setattr(state, "_daemon_request", request)
    with pytest.raises(RuntimeError, match="paused step jobs"):
        state.restart_bundle(tmp_path, 8135)
    assert actions == ["drain", "resume"]
