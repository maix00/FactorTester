"""Focused federation behavior tests."""

from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import pytest
from server.manager import runtime as manager
from server.manager.domain.federation import FederationSyncWorker
from server.manager.http.peer_handler import peer_control_handler

def test_federation_sync_worker_advances_cursor_and_is_idempotent(tmp_path) -> None:
    origin = manager.ManagerState(
        tmp_path / "origin-repo",
        "python",
        server_role="feat",
        server_id="origin",
        state_root=tmp_path / "origin-state",
    )
    origin.job_index.record_run_routing(
        run_id="run-1",
        principal="alice",
        origin_server_id="origin",
        execution_server_id="peer",
        execution_port=8000,
    )
    events = origin.job_index.events_for_peer("peer")["events"]

    peer = manager.ManagerState(
        tmp_path / "peer-repo",
        "python",
        server_role="main",
        server_id="peer",
        state_root=tmp_path / "peer-state",
    )

    class FakeGateway:
        def __init__(self) -> None:
            self.calls = 0

        def sync_events(self, route, *, requester_server_id, after_sequence):
            self.calls += 1
            assert route.server_id == "origin"
            assert requester_server_id == "peer"
            if after_sequence:
                return {
                    "success": True,
                    "events": [],
                    "next_sequence": after_sequence,
                }
            return {
                "success": True,
                "events": events,
                "next_sequence": events[-1]["sequence"],
            }

    gateway = FakeGateway()
    worker = FederationSyncWorker(
        server_id="peer",
        job_index=peer.job_index,
        gateway=gateway,
        peer_provider=lambda: [{
            "server_id": "origin",
            "endpoint": "http://origin:7998",
            "proxy_token": "token",
            "online": True,
        }],
    )
    first = worker.sync_once()
    second = worker.sync_once()

    assert first[0]["applied"] == 1
    assert second[0]["received"] == 0
    assert peer.job_index.sync_cursor("origin") == events[-1]["sequence"]
    assert gateway.calls == 2


def test_federation_sync_worker_runs_local_maintenance(tmp_path) -> None:
    calls: list[str] = []

    class _Index:
        pass

    worker = FederationSyncWorker(
        server_id="local",
        job_index=_Index(),
        gateway=object(),
        peer_provider=lambda: [],
        local_maintenance=lambda: calls.append("maintenance"),
    )

    assert worker.sync_once() == []
    assert calls == ["maintenance"]


def test_manager_sync_endpoints_use_authenticated_peer_control_plane(tmp_path) -> None:
    state = manager.ManagerState(
        tmp_path / "target-repo",
        "python",
        server_role="main",
        server_id="target",
        state_root=tmp_path / "target-state",
    )
    state.federation_proxy_path.write_text("proxy-token", encoding="ascii")
    state.job_index.upsert("alice", [{
        "job_id": "job-1",
        "run_id": "run-1",
        "port": 8000,
        "server_id": "target",
        "origin_server_id": "peer",
        "execution_server_id": "target",
        "updated_at": "2026-08-06T00:01:00Z",
    }])
    server = manager.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        peer_control_handler(state),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        body = json.dumps({
            "requester_server_id": "peer",
            "after_sequence": 0,
            "limit": 100,
        }).encode()
        request = Request(
            f"{base_url}/api/federation/sync/events",
            data=body,
            headers={
                "Authorization": "Bearer proxy-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request) as response:
            events = json.loads(response.read())
        assert response.status == 200
        assert events["source_server_id"] == "target"
        assert events["events"][0]["audience"] == ["peer", "target"]

        reconcile = Request(
            f"{base_url}/api/federation/sync/reconcile",
            data=json.dumps({
                "requester_server_id": "peer",
                "job_ids": ["job-1"],
            }).encode(),
            headers={
                "Authorization": "Bearer proxy-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(reconcile) as response:
            snapshot = json.loads(response.read())
        assert response.status == 200
        assert snapshot["jobs"][0]["job"]["job_id"] == "job-1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_manual_manager_sync_requires_admin_and_returns_worker_report(tmp_path) -> None:
    state = manager.ManagerState(
        tmp_path / "manual-repo",
        "python",
        server_role="feat",
        server_id="manual",
        state_root=tmp_path / "manual-state",
    )
    state._sessions[state._token_hash("admin-token")] = (
        "admin@1", "super_admin", float("inf"),
    )
    state.sync_federation_once = lambda: [{
        "server_id": "peer",
        "status": "ok",
        "received": 1,
        "applied": 1,
    }]
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        unauthenticated = Request(
            f"{base_url}/api/federation/sync",
            data=b"{}",
            method="POST",
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(unauthenticated)
        assert denied.value.code == 401

        authenticated = Request(
            f"{base_url}/api/federation/sync",
            data=b"{}",
            headers={"Authorization": "Bearer admin-token"},
            method="POST",
        )
        with urlopen(authenticated) as response:
            value = json.loads(response.read())
        assert response.status == 200
        assert value["reports"][0]["applied"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
