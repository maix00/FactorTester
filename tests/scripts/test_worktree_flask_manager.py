from __future__ import annotations

from pathlib import Path

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
