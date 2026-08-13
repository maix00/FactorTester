from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from server.manager import runtime as manager
from server.manager.domain.federation import (
    FederationConfigStore,
    FederatedGateway,
    FederatedServerRegistry,
    FederationSyncWorker,
    ServiceRoute,
    TargetUnavailable,
)
from server.manager.services.network_info import local_internal_addresses
from server.manager.http.peer_handler import peer_control_handler


def _registration(
    server_id: str,
    *,
    latency_ms: float,
    load: float,
    port: int = 8000,
    online: bool = True,
) -> dict[str, object]:
    return {
        "server_id": server_id,
        "role": "main",
        "branch": "main",
        "revision": "abc123",
        "endpoint": f"http://{server_id}:7998",
        "proxy_token": f"proxy-{server_id}",
        "latency_ms": latency_ms,
        "load": {"load": load, "active_jobs": 1, "queue_depth": 2},
        "ports": [{
            "port": port,
            "branch": "main",
            "online": online,
            "load": {"load": load, "active_jobs": 1, "queue_depth": 2},
        }],
    }


def test_federation_config_public_view_redacts_registration_token(tmp_path) -> None:
    store = FederationConfigStore(tmp_path / "federation.json")
    saved = store.save({
        "enabled": True,
        "register_url": "http://10.77.0.2:17998/api/federation/register",
        "public_endpoint": "https://this.example:7998",
        "registration_token": "secret-token",
        "ports": [7999, 8141],
        "interval": 10,
    })

    public = store.public(saved)
    assert public["ports"] == [7999, 8141]
    assert "registration_token" not in public
    assert public["registration_token_configured"] is True


def test_federation_config_rejects_public_control_plane_registration(
    tmp_path,
) -> None:
    store = FederationConfigStore(tmp_path / "federation.json")

    with pytest.raises(ValueError, match="WireGuard IP on port 17998"):
        store.save({
            "enabled": True,
            "register_url": (
                "https://8.8.8.8:7998/api/federation/register"
            ),
            "public_endpoint": "https://198.51.100.20:7998",
            "registration_token": "secret-token",
        })


def test_registry_exposes_port_load_and_offline_lease(tmp_path) -> None:
    registry = FederatedServerRegistry(tmp_path / "registry.json", lease_seconds=5)
    registry.register(_registration("peer-a", latency_ms=8, load=3))
    route = registry.find(server_id="peer-a", port=8000)

    assert route.remote is True
    assert route.endpoint == "http://peer-a:7998"
    assert route.load == 3
    assert route.active_jobs == 1
    assert route.queue_depth == 2
    assert route.latency_ms == 8

    registry._servers["peer-a"]["last_seen"] = time.time() - 100
    with pytest.raises(TargetUnavailable):
        registry.find(server_id="peer-a", port=8000)


def test_registry_keeps_an_online_manager_with_no_execution_ports(tmp_path) -> None:
    registry = FederatedServerRegistry(tmp_path / "registry.json", lease_seconds=5)
    value = _registration("peer-empty", latency_ms=8, load=0)
    value["ports"] = []

    registered = registry.register(value)

    assert registered["ports"] == []
    assert registry.servers(include_offline=False)[0]["server_id"] == "peer-empty"


def test_unqualified_route_prefers_nearest_then_least_loaded(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_role="feat",
        server_id="local-feat",
        state_root=tmp_path / "manager-state",
    )
    monkeypatch.setattr(state, "local_service_routes", lambda include_offline=True: [])
    state.federation_registry.register(
        _registration("peer-near", latency_ms=5, load=50),
    )
    state.federation_registry.register(
        _registration("peer-far", latency_ms=30, load=1),
    )

    assert state.route_for().server_id == "peer-near"

    state.federation_registry._servers["peer-near"]["latency_ms"] = 30
    assert state.route_for().server_id == "peer-far"


def test_public_device_targets_are_server_discovered_https_peers(tmp_path) -> None:
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_role="feat",
        server_id="internal-feat",
        state_root=tmp_path / "manager-state",
    )
    near = _registration("public-near", latency_ms=6, load=8)
    near["endpoint"] = "https://198.51.100.10:7998"
    far = _registration("public-far", latency_ms=25, load=1)
    far["endpoint"] = "https://198.51.100.20:7998"
    insecure = _registration("insecure", latency_ms=1, load=0)
    state.federation_registry.register(far)
    state.federation_registry.register(insecure)
    state.federation_registry.register(near)

    targets = state.public_device_targets()
    info = state.server_network_info()

    assert [item["server_id"] for item in targets] == [
        "public-near",
        "public-far",
    ]
    assert info["current_public_target"]["server_id"] == "public-near"
    assert info["public_server"] is False
    assert info["internal_addresses"]
    assert info["manager_port"] == 7998
    assert all(item["endpoint"].startswith("https://") for item in targets)


def test_lan_addresses_exclude_loopback_and_local_only_values() -> None:
    assert local_internal_addresses(configured=[
        "127.0.0.1",
        "0.0.0.0",
        "169.254.1.5",
        "192.168.50.10",
        "192.168.50.10",
    ]) == ["192.168.50.10"]


def test_configured_lan_addresses_override_container_hostname_discovery(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_LAN_ADDRESSES", "192.168.50.10")

    assert local_internal_addresses(hostnames=["container-hostname"]) == [
        "192.168.50.10",
    ]


def test_public_manager_network_info_uses_its_request_endpoint(tmp_path) -> None:
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_role="main",
        server_id="public-main",
        state_root=tmp_path / "manager-state",
    )
    state.public_server = True

    info = state.server_network_info(
        request_endpoint="https://198.51.100.10:7998",
    )

    assert info["public_server"] is True
    assert info["advertised_public_endpoint"] == "https://198.51.100.10:7998"
    assert info["current_public_target"] is None


def test_unqualified_route_uses_fixed_local_service_when_no_peer(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_role="main",
        server_id="local-main",
        fixed_port=8000,
        fixed_branch="main",
        state_root=tmp_path / "manager-state",
    )
    local = ServiceRoute(
        server_id="local-main",
        role="main",
        branch="main",
        revision="abc123",
        port=8000,
        online=True,
        latency_ms=0,
    )
    monkeypatch.setattr(state, "local_service_routes", lambda include_offline=True: [local])
    monkeypatch.setattr(state, "preferred_service_port", lambda: 8000)

    assert state.route_for().server_id == "local-main"
    assert state.route_for().port == 8000


def test_federated_gateway_reaches_service_only_through_peer_manager(tmp_path) -> None:
    class ServiceHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path.endswith("/stream"):
                body = b'data: {"job_id":"job-1","status":"running"}\n\n'
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = json.dumps({"success": True, "job_id": "job-1"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:
            return

    service = ThreadingHTTPServer(("127.0.0.1", 0), ServiceHandler)
    service_thread = threading.Thread(target=service.serve_forever, daemon=True)
    service_thread.start()
    service_port = service.server_address[1]
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_role="main",
        server_id="remote-main",
        fixed_port=service_port,
        fixed_branch="main",
        state_root=tmp_path / "manager-state",
    )
    state.capability_path.write_text("manager-capability", encoding="ascii")
    state.federation_proxy_path.write_text("proxy-token", encoding="ascii")
    gateway = manager.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        peer_control_handler(state),
    )
    manager_thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    manager_thread.start()
    endpoint = f"http://127.0.0.1:{gateway.server_address[1]}"
    route = ServiceRoute(
        server_id="remote-main",
        role="main",
        branch="main",
        revision="abc123",
        port=service_port,
        endpoint=endpoint,
        peer_control_endpoint=endpoint,
        proxy_token="proxy-token",
        remote=True,
        online=True,
    )
    federated = FederatedGateway(timeout=3)
    try:
        response = federated.request(
            route,
            path="/api/jobs/job-1",
            principal="user@1",
        )
        assert response.status == 200
        assert response.json_object()["job_id"] == "job-1"

        with federated.open_stream(
            route,
            path="/api/jobs/job-1/stream",
            principal="user@1",
        ) as stream:
            assert b"job-1" in stream.read()

        capability = federated.capabilities(
            route,
            payload={"summary": True},
        )
        assert capability["target"]["server_id"] == "remote-main"
        assert capability["target"]["port"] == service_port
        assert capability["target"]["branch"] == "main"
        assert capability["ports"][0]["port"] == service_port
    finally:
        gateway.shutdown()
        gateway.server_close()
        manager_thread.join(timeout=2)
        service.shutdown()
        service.server_close()
        service_thread.join(timeout=2)


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


def test_cross_server_jobs_are_fetched_on_demand_without_local_projection_sync(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path / "cross-repo",
        "python",
        server_role="feat",
        server_id="local-feat",
        state_root=tmp_path / "cross-state",
    )
    state.federation_registry.register(
        _registration("remote-main", latency_ms=8, load=1),
    )
    local_calls = []

    def local_jobs(**kwargs):
        local_calls.append(kwargs)
        return {
            "jobs": [{
                "job_id": "local-job", "port": 8141,
                "owner": "alice", "updated_at": "2026-08-12T00:02:00Z",
            }],
            "total": 1, "has_more": False,
        }

    monkeypatch.setattr(state, "aggregate_account_jobs", local_jobs)
    monkeypatch.setattr(
        state,
        "_federation_manager_routes",
        lambda: [state.federation_registry.find(server_id="remote-main", port=8000)],
    )

    class Gateway:
        def query_jobs(self, route, **kwargs):
            assert route.server_id == "remote-main"
            assert kwargs["scope"] == "mine"
            return {
                "jobs": [{
                    "job_id": "remote-job", "port": 8000,
                    "owner": "alice", "updated_at": "2026-08-12T00:03:00Z",
                }],
                "total": 1, "has_more": False,
            }

    state.federation_gateway = Gateway()
    payload = state.aggregate_cross_server_jobs(
        principal="alice", source_scope="mine", limit=20,
    )

    assert payload["sync_mode"] == "on_demand"
    assert [item["job_id"] for item in payload["jobs"]] == [
        "remote-job", "local-job",
    ]
    assert [item["server_id"] for item in payload["jobs"]] == [
        "remote-main", "local-feat",
    ]
    assert local_calls[0]["_allow_federation"] is False


def test_peer_job_query_endpoint_is_authenticated_and_local_only(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(
        tmp_path / "query-repo",
        "python",
        server_role="main",
        server_id="remote-main",
        state_root=tmp_path / "query-state",
    )
    state.federation_proxy_path.write_text("proxy-token", encoding="ascii")
    calls = []

    def local_jobs(**kwargs):
        calls.append(kwargs)
        return {"jobs": [{"job_id": "remote-job", "port": 8000}], "total": 1}

    monkeypatch.setattr(state, "aggregate_account_jobs", local_jobs)
    server = manager.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        peer_control_handler(state),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        request = Request(
            f"{base_url}/api/federation/jobs/query",
            data=json.dumps({
                "requester_server_id": "local-feat",
                "principal": "alice",
                "scope": "mine",
                "page": 1,
                "limit": 20,
            }).encode(),
            headers={
                "Authorization": "Bearer proxy-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request) as response:
            value = json.loads(response.read())
        assert response.status == 200
        assert value["source_server_id"] == "remote-main"
        assert calls == [{
            "principal": "alice",
            "scope": "mine",
            "page": 1,
            "limit": 20,
            "_allow_federation": False,
        }]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
