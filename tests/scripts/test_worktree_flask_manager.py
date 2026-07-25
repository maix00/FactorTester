from __future__ import annotations

import os
import json
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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


@contextmanager
def _running_manager(state):
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_manager_binds_loopback_by_default(tmp_path, monkeypatch) -> None:
    observed = {}

    class _Server:
        def __init__(self, address, handler):
            observed["address"] = address

        def serve_forever(self):
            return None

        def server_close(self):
            return None

    monkeypatch.setattr(manager, "ThreadingHTTPServer", _Server)
    monkeypatch.setattr(manager.ManagerState, "stop_all", lambda self: None)
    monkeypatch.setattr(manager.webbrowser, "open", lambda _url: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["worktree_flask_manager.py", "--repo", str(tmp_path), "--no-browser"],
    )

    assert manager.main() == 0
    assert observed["address"] == ("127.0.0.1", 7998)


def test_worktree_api_requires_shared_bearer_token(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.secret_path.parent.mkdir(parents=True, exist_ok=True)
    (state.secret_path.parent / "manager-capability.key").write_text(
        "test-capability", encoding="ascii"
    )
    monkeypatch.setattr(state, "worktrees", lambda: [])

    with _running_manager(state) as base_url:
        with pytest.raises(HTTPError) as denied:
            urlopen(f"{base_url}/api/worktrees")
        assert denied.value.code == 401

        request = Request(
            f"{base_url}/api/worktrees",
            headers={"Authorization": "Bearer test-capability"},
        )
        with urlopen(request) as response:
            assert response.status == 200


def test_manager_login_issues_ui_session_for_api_access(
    tmp_path, monkeypatch
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("internal-capability", encoding="ascii")
    monkeypatch.setattr(state, "worktrees", lambda: [])
    monkeypatch.setattr(
        manager,
        "_authenticate_manager_user",
        lambda username, password: (
            "root@1"
            if (username, password) == ("root", "secret")
            else (_ for _ in ()).throw(PermissionError("invalid"))
        ),
    )

    with _running_manager(state) as base_url:
        login = Request(
            f"{base_url}/auth/login",
            data=json.dumps({
                "username": "root",
                "password": "secret",
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(login) as response:
            session = json.loads(response.read())
        request = Request(
            f"{base_url}/api/worktrees",
            headers={"Authorization": f"Bearer {session['token']}"},
        )
        with urlopen(request) as response:
            assert response.status == 200

    assert session["username"] == "root@1"
    assert session["role"] == "super_admin"


def test_remote_browser_page_is_rejected_even_before_login(
    tmp_path, monkeypatch
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    monkeypatch.setattr(
        manager.Handler,
        "_is_loopback_client",
        lambda _self: False,
    )

    with _running_manager(state) as base_url:
        with pytest.raises(HTTPError) as denied:
            urlopen(f"{base_url}/")

    assert denied.value.code == 403
    assert "only supports localhost" in denied.value.read().decode()


def test_remote_ui_login_requires_https(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    monkeypatch.setattr(
        manager.Handler,
        "_is_loopback_client",
        lambda _self: False,
    )

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/auth/login",
            data=b'{"username":"root","password":"secret"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(request)

    assert denied.value.code == 400
    assert "requires HTTPS" in denied.value.read().decode()


def test_capability_token_is_created_atomically_with_owner_only_mode(
    tmp_path, monkeypatch
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    monkeypatch.setattr(Path, "chmod", lambda self, mode: None)
    previous_umask = os.umask(0)
    try:
        token = state.capability_token()
    finally:
        os.umask(previous_umask)

    assert token
    assert state.capability_path.stat().st_mode & 0o777 == 0o600


def test_worktree_api_uses_opaque_instance_id_without_absolute_path(
    tmp_path, monkeypatch
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    source = tmp_path / "private" / "issue-141"
    worktree = manager.Worktree(
        path=source,
        branch="fix/issue-141-secure-manager",
        head="abcdef12",
        label="fix/issue-141-secure-manager",
        port=8141,
    )
    monkeypatch.setattr(state, "worktrees", lambda: [worktree])
    monkeypatch.setattr(manager, "port_in_use", lambda _port: False)

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/worktrees",
            headers={"Authorization": "Bearer test-capability"},
        )
        with urlopen(request) as response:
            raw = response.read().decode("utf-8")

    payload = json.loads(raw)
    item = payload["worktrees"][0]
    assert item["instance_id"].startswith("worktree-")
    assert "path" not in item
    assert str(source) not in raw


def test_mutation_rejects_legacy_path_and_port_payload(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    called = []
    monkeypatch.setattr(
        state,
        "restart_bundle",
        lambda path, port: called.append((path, port)) or "restarted",
    )

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/restart-bundle",
            data=urlencode({"path": str(tmp_path), "port": "8141"}).encode(),
            headers={
                "Authorization": "Bearer test-capability",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(request)

    assert denied.value.code == 400
    assert called == []


@pytest.mark.parametrize(
    "action",
    [
        "start", "stop", "restart-api", "restart-bundle", "force-stop",
        "vibe/start", "vibe/stop",
    ],
)
def test_every_mutation_requires_bearer_capability(tmp_path, action) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/{action}",
            data=urlencode({"instance_id": "untrusted"}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(request)

    assert denied.value.code == 401


def test_mutation_resolves_opaque_instance_id_server_side(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    source = tmp_path / "private" / "issue-141"
    worktree = manager.Worktree(
        path=source,
        branch="fix/issue-141-secure-manager",
        head="abcdef12",
        label="fix/issue-141-secure-manager",
        port=8141,
    )
    monkeypatch.setattr(state, "worktrees", lambda: [worktree])
    called = []
    monkeypatch.setattr(
        state,
        "restart_bundle",
        lambda path, port: called.append((path, port)) or "restarted",
    )
    instance_id = state.instance_id(worktree)

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/restart-bundle",
            data=urlencode({"instance_id": instance_id}).encode(),
            headers={
                "Authorization": "Bearer test-capability",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urlopen(request) as response:
            raw = response.read().decode("utf-8")

    assert called == [(source, 8141)]
    assert json.loads(raw) == {
        "success": True,
        "instance_id": instance_id,
        "message": "restarted",
    }
    assert str(source) not in raw


def test_async_mutation_responds_before_the_destructive_action(
    tmp_path,
    monkeypatch,
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    source = tmp_path / "private" / "issue-141"
    worktree = manager.Worktree(
        path=source,
        branch="fix/issue-141-secure-manager",
        head="abcdef12",
        label="fix/issue-141-secure-manager",
        port=8141,
    )
    monkeypatch.setattr(state, "worktrees", lambda: [worktree])
    called = []
    scheduled = []
    monkeypatch.setattr(
        state,
        "restart_bundle",
        lambda path, port: called.append((path, port)) or "restarted",
    )
    monkeypatch.setattr(
        state,
        "submit_action",
        lambda operation, label: scheduled.append((operation, label)),
    )
    instance_id = state.instance_id(worktree)

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/restart-bundle",
            data=urlencode({"instance_id": instance_id}).encode(),
            headers={
                "Authorization": "Bearer test-capability",
                "Content-Type": "application/x-www-form-urlencoded",
                "Prefer": "respond-async",
            },
            method="POST",
        )
        with urlopen(request) as response:
            raw = response.read().decode("utf-8")
            assert response.status == 202

    assert json.loads(raw) == {
        "success": True,
        "submitted": True,
        "instance_id": instance_id,
    }
    assert called == []
    operation, label = scheduled[0]
    assert label == f"/restart-bundle {instance_id}"
    operation()
    assert called == [(source, 8141)]


def test_mutation_error_does_not_disclose_managed_path(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    source = tmp_path / "private" / "issue-141"
    worktree = manager.Worktree(
        path=source,
        branch="fix/issue-141-secure-manager",
        head="abcdef12",
        label="fix/issue-141-secure-manager",
        port=8141,
    )
    monkeypatch.setattr(state, "worktrees", lambda: [worktree])

    def fail(_path, _port):
        raise RuntimeError(f"failed under {source}")

    monkeypatch.setattr(state, "restart_bundle", fail)
    instance_id = state.instance_id(worktree)

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/restart-bundle",
            data=urlencode({"instance_id": instance_id}).encode(),
            headers={
                "Authorization": "Bearer test-capability",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as failed:
            urlopen(request)
        raw = failed.value.read().decode("utf-8")

    assert failed.value.code == 409
    assert str(source) not in raw


def test_manager_page_allows_loopback_browser_without_leaking_paths(
    tmp_path, monkeypatch
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    source = tmp_path / "private" / "issue-141"
    worktree = manager.Worktree(
        path=source,
        branch="fix/issue-141-secure-manager",
        head="abcdef12",
        label="fix/issue-141-secure-manager",
        port=8141,
    )
    monkeypatch.setattr(state, "worktrees", lambda: [worktree])
    monkeypatch.setattr(manager, "port_in_use", lambda _port: False)

    with _running_manager(state) as base_url:
        with urlopen(f"{base_url}/") as response:
            body = response.read().decode("utf-8")

    assert str(source) not in body
    assert str(manager.VIBE_TRADING_ROOT) not in body
    assert 'name="path"' not in body
    assert 'name="port"' not in body
    assert 'name="instance_id"' in body


def test_loopback_browser_can_submit_same_origin_action(
    tmp_path, monkeypatch
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    source = tmp_path / "private" / "issue-141"
    worktree = manager.Worktree(
        path=source,
        branch="fix/issue-141-secure-manager",
        head="abcdef12",
        label="fix/issue-141-secure-manager",
        port=8141,
    )
    monkeypatch.setattr(state, "worktrees", lambda: [worktree])
    called = []
    monkeypatch.setattr(
        state,
        "start",
        lambda path, port: called.append((path, port)) or "started",
    )

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/start",
            data=urlencode({
                "instance_id": state.instance_id(worktree),
            }).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": base_url,
            },
            method="POST",
        )
        with urlopen(request) as response:
            assert response.status == 200

    assert called == [(source, 8141)]


@pytest.mark.parametrize("branch", ["main", "master"])
def test_primary_branch_uses_fixed_port_8000(tmp_path, monkeypatch, branch) -> None:
    worktree = tmp_path / "repo"
    worktree.mkdir()
    porcelain = (
        f"worktree {worktree}\n"
        "HEAD abcdef1234567890\n"
        f"branch refs/heads/{branch}\n\n"
    )
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: porcelain,
    )

    result = manager.ManagerState(worktree, "python").worktrees()

    assert len(result) == 1
    assert result[0].branch == branch
    assert result[0].port == 8000


def test_cleanup_detached_worktrees_removes_snapshots_and_prunes(tmp_path, monkeypatch) -> None:
    detached = tmp_path / "detached"
    detached.mkdir()
    porcelain = (
        f"worktree {tmp_path}\n"
        "HEAD e5707434d001991c89871f743a0583086d393c6e\n"
        "branch refs/heads/main\n\n"
        f"worktree {detached}\n"
        "HEAD 689e141e78c90d5cbb6d7b96e236919056db7525\n"
        "detached\n\n"
    )
    commands = []
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: porcelain,
    )
    monkeypatch.setattr(
        manager.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command),
    )
    state = manager.ManagerState(tmp_path, "python")

    removed = state.cleanup_detached_worktrees()

    assert removed == [detached.resolve()]
    assert commands[0][:4] == ["git", "worktree", "remove", "--force"]
    assert commands[1] == ["git", "worktree", "prune", "--expire", "now"]


def test_cleanup_detached_worktrees_leaves_missing_paths_to_prune(tmp_path, monkeypatch) -> None:
    missing = tmp_path / "missing-detached"
    porcelain = (
        f"worktree {tmp_path}\n"
        "HEAD e5707434d001991c89871f743a0583086d393c6e\n"
        "branch refs/heads/main\n\n"
        f"worktree {missing}\n"
        "HEAD 689e141e78c90d5cbb6d7b96e236919056db7525\n"
        "detached\n\n"
    )
    commands = []
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: porcelain,
    )
    monkeypatch.setattr(
        manager.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command),
    )
    state = manager.ManagerState(tmp_path, "python")

    assert state.cleanup_detached_worktrees() == []
    assert commands == [["git", "worktree", "prune", "--expire", "now"]]


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
    assert created[1][1]["env"]["FACTORTESTER_WERKZEUG_RELOADER"] == "0"
    assert created[1][1]["env"]["FLASK_SECRET_KEY"]
    assert created[1][1]["env"]["FLASK_SECRET_KEY"] == created[2][1]["env"]["FLASK_SECRET_KEY"]
    assert "GTHT_MANAGER_CAPABILITY_TOKEN" not in created[0][1]["env"]
    assert created[1][1]["env"]["GTHT_MANAGER_CAPABILITY_TOKEN"]
    assert created[2][1]["env"]["GTHT_MANAGER_CAPABILITY_TOKEN"]
    assert (tmp_path / ".workspace" / "flask-manager" / "flask-secret.key").stat().st_mode & 0o777 == 0o600


def test_service_env_adds_repo_harness_without_losing_pythonpath(
    tmp_path,
    monkeypatch,
) -> None:
    existing = os.pathsep.join(["/existing/one", "/existing/two"])
    monkeypatch.setenv("PYTHONPATH", existing)
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: "abc123\n",
    )
    state = manager.ManagerState(tmp_path, "python")

    env, _, _ = state._service_env(tmp_path, 8000)

    harness = str((tmp_path / "tools/cli/agent-harness").resolve())
    entries = env["PYTHONPATH"].split(os.pathsep)
    assert entries == [harness, "/existing/one", "/existing/two"]
    assert entries.count(harness) == 1


def test_bundle_restart_recovers_api_when_daemon_has_died(
    tmp_path,
    monkeypatch,
) -> None:
    (tmp_path / "start_server.py").write_text("", encoding="ascii")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "research_job_daemon.py").write_text(
        "", encoding="ascii"
    )
    old_api = _Process(["api"])
    dead_daemon = _Process(["daemon"])
    dead_daemon.returncode = 1
    state = manager.ManagerState(tmp_path, "python")
    state.processes[state.key(tmp_path)] = manager.ServiceBundle(
        api=old_api,
        daemon=dead_daemon,
        socket_path=tmp_path / "jobs.sock",
        deployment_id="test",
    )
    monkeypatch.setattr(manager, "port_in_use", lambda _port: False)
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: "abc123\n",
    )
    monkeypatch.setattr(
        manager.subprocess,
        "Popen",
        lambda command, **kwargs: _Process(command),
    )
    monkeypatch.setattr(
        manager.ManagerState,
        "_terminate",
        staticmethod(lambda process: setattr(process, "returncode", 0)),
    )

    state.restart_bundle(tmp_path, 8135)

    replacement = state.processes[state.key(tmp_path)]
    assert old_api.returncode == 0
    assert replacement.api is not old_api
    assert replacement.api.poll() is None
    assert replacement.daemon.poll() is None


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


def test_manager_starts_and_stops_vibe_on_fixed_port(tmp_path, monkeypatch) -> None:
    vibe_root = tmp_path / "Vibe-Trading-Integration"
    executable = vibe_root / ".conda" / "bin" / "vibe-trading"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="ascii")
    created = []

    def fake_popen(command, **kwargs):
        process = _Process(command)
        created.append((process, kwargs))
        return process

    monkeypatch.setattr(manager, "VIBE_TRADING_ROOT", vibe_root)
    monkeypatch.setattr(manager, "port_in_use", lambda port: False)
    monkeypatch.setattr(manager.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        manager.ManagerState,
        "_terminate",
        staticmethod(lambda process: setattr(process, "returncode", 0)),
    )
    state = manager.ManagerState(tmp_path, "python")

    message = state.start_vibe()

    assert "started Vibe-Trading" in message
    assert state.vibe_running()
    assert created[0][0].command == [
        str(executable),
        "serve",
        "--host", "127.0.0.1",
        "--port", "7899",
    ]
    assert created[0][1]["cwd"] == vibe_root
    assert state.stop_vibe() == "stopped Vibe-Trading"
    assert not state.vibe_running()


def test_manager_page_exposes_vibe_controls(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(manager.ManagerState, "worktrees", lambda self: [])
    monkeypatch.setattr(manager, "port_in_use", lambda port: False)
    state = manager.ManagerState(tmp_path, "python")

    body = manager.page(state).decode()

    assert "Vibe-Trading" in body
    assert "http://localhost:7899/" in body
    assert 'action="/vibe/start"' in body
    assert 'action="/vibe/stop"' in body
