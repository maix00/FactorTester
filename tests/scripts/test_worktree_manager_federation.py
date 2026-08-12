from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest

from scripts import worktree_flask_manager as manager
from scripts.worktree_manager_federation import (
    FederationConfigStore,
    FederatedGateway,
    FederatedServerRegistry,
    ServiceRoute,
    TargetUnavailable,
)


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
        "register_url": "https://peer.example/api/federation/register",
        "public_endpoint": "https://this.example:7998",
        "registration_token": "secret-token",
        "ports": [7999, 8141],
        "interval": 10,
    })

    public = store.public(saved)
    assert public["ports"] == [7999, 8141]
    assert "registration_token" not in public
    assert public["registration_token_configured"] is True


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
    manager.Handler.state = state
    gateway = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
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
    finally:
        gateway.shutdown()
        gateway.server_close()
        manager_thread.join(timeout=2)
        service.shutdown()
        service.server_close()
        service_thread.join(timeout=2)
