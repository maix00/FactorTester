"""Focused federation behavior tests."""

from __future__ import annotations

import json
import time
from urllib.parse import urlparse

import pytest

from server.manager import runtime as manager
from server.manager.domain.federation import (
    FederatedServerRegistry,
    FederationConfigStore,
    ServiceRoute,
    TargetUnavailable,
)
from server.manager.network_endpoints import server_endpoints
from tests.federation_fixtures import federation_registration as _registration


def test_federation_config_public_view_redacts_registration_token(tmp_path) -> None:
    store = FederationConfigStore(tmp_path / "federation.json")
    saved = store.save({
        "enabled": True,
        "bootstrap_url": "http://10.77.0.2:17998/api/federation/register",
        "public_endpoint": "https://this.example:7998",
        "registration_token": "secret-token",
        "ports": [7999, 8141],
        "interval": 10,
    })

    public = store.public(saved)
    assert public["bootstrap_url"] == (
        "http://10.77.0.2:17998/api/federation/register"
    )
    assert "register_url" not in public
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


def test_legacy_register_url_is_loaded_as_one_bootstrap_node(tmp_path) -> None:
    path = tmp_path / "federation.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "enabled": True,
        "register_url": "http://10.77.0.2:17998/api/federation/register",
        "public_endpoint": "https://this.example:7998",
        "registration_token": "secret-token",
        "ports": [],
        "interval": 10,
    }), encoding="utf-8")

    loaded = FederationConfigStore(path).load()

    assert loaded["schema_version"] == 2
    assert loaded["bootstrap_url"] == (
        "http://10.77.0.2:17998/api/federation/register"
    )
    assert "register_url" not in loaded


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


def test_job_analysis_skips_unrelated_offline_peer(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_role="main",
        server_id="remote-main",
        fixed_port=8000,
        fixed_branch="main",
        state_root=tmp_path / "manager-state",
    )
    online = ServiceRoute(
        server_id="remote-main",
        role="main",
        branch="main",
        revision="a" * 40,
        port=8000,
        remote=False,
        online=True,
    )
    offline = ServiceRoute(
        server_id="local-feat",
        role="feat",
        branch="feat",
        revision="b" * 40,
        port=8141,
        remote=True,
        online=False,
    )
    monkeypatch.setattr(
        state.federation_registry,
        "servers",
        lambda include_offline=False: (
            [{"server_id": offline.server_id}] if include_offline else []
        ),
    )
    monkeypatch.setattr(
        state,
        "service_routes",
        lambda include_offline=False: [online, offline]
        if include_offline else [online],
    )
    manager.Handler.state = state
    handler = object.__new__(manager.Handler)

    routes = handler._job_routes(
        urlparse("/api/jobs/job-1/group-snapshot"),
        "alice",
    )

    assert routes == [online]


def test_explicit_self_route_survives_missing_worktree_metadata(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_role="main",
        server_id="remote-main",
        fixed_port=8000,
        fixed_branch="main",
        state_root=tmp_path / "manager-state",
    )
    monkeypatch.setattr(state, "local_service_routes", lambda include_offline=True: [])
    monkeypatch.setattr(state, "service_ports", lambda: [8000])

    route = state.route_for(server_id="remote-main", port=8000)

    assert route.server_id == "remote-main"
    assert route.port == 8000
    assert route.branch == "main"


def _federated_state(tmp_path, server_id: str, octet: int):
    root = tmp_path / server_id
    root.mkdir()
    state = manager.ManagerState(
        root,
        "python",
        server_role="feat",
        server_id=server_id,
        state_root=root / "manager-state",
    )
    state.configure_transfer_endpoints(server_endpoints(
        client_control_endpoint=f"https://{server_id}.example:7998",
        client_data_endpoint=f"https://{server_id}.example:7997",
        overlay_bind_address=f"10.77.0.{octet}",
    ))
    return state


def _catalog_entry(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"endpoint", "proxy_token", "latency_ms"}
    }


def test_one_bootstrap_discovers_nodes_then_registers_them_directly(tmp_path) -> None:
    state = _federated_state(tmp_path, "node-a", 10)
    bootstrap = _federated_state(tmp_path, "node-b", 11)
    third = _federated_state(tmp_path, "node-c", 12)
    bootstrap_payload = bootstrap.registration_payload(
        "https://node-b.example:7998",
    )
    third_payload = third.registration_payload(
        "https://node-c.example:7998",
    )

    direct_urls = state.accept_federation_catalog({
        "success": True,
        "bootstrap_server_id": "node-b",
        "peer": bootstrap_payload,
        "nodes": [
            _catalog_entry(bootstrap_payload),
            _catalog_entry(third_payload),
        ],
        "_roundtrip_ms": 7,
    })

    registered = state.federation_registry.servers(include_offline=True)
    assert {item["server_id"] for item in registered} == {"node-b"}
    assert state.federation_registry.describe("node-b")["latency_ms"] == 7
    assert state.federation_registry.describe("node-c") is None
    assert direct_urls == (
        "http://10.77.0.12:17998/api/federation/register",
    )


def test_replayed_catalog_does_not_refresh_direct_route_lease(tmp_path) -> None:
    receiver = _federated_state(tmp_path, "node-a", 10)
    sender = _federated_state(tmp_path, "node-b", 11)
    peer = sender.registration_payload("https://node-b.example:7998")
    response = {
        "bootstrap_server_id": "node-b",
        "peer": peer,
        "nodes": [],
        "_roundtrip_ms": 7,
    }

    receiver.accept_federation_catalog(response)
    receiver.federation_registry._servers["node-b"]["last_seen"] = 1.0
    receiver.accept_federation_catalog(response)

    assert receiver.federation_registry.describe("node-b")["last_seen"] == 1.0


def test_discovered_route_authenticates_only_when_selected(tmp_path) -> None:
    state = _federated_state(tmp_path, "node-a", 10)
    bootstrap = _federated_state(tmp_path, "node-b", 11)
    third = _federated_state(tmp_path, "node-c", 12)
    bootstrap_payload = bootstrap.registration_payload(
        "https://node-b.example:7998",
    )
    third_payload = third.registration_payload(
        "https://node-c.example:7998",
    )
    third_payload["ports"] = [{
        "port": 8141,
        "branch": "fix/issue-141-demo",
        "revision": "c" * 40,
        "features": ["research"],
        "online": True,
        "load": {"load": 1, "active_jobs": 0, "queue_depth": 1},
    }]

    class LazyAnnouncer:
        calls: list[tuple[str, str]] = []

        def activate(self, server_id: str, registration_url: str) -> None:
            self.calls.append((server_id, registration_url))
            state.accept_federation_registration(
                third_payload,
                observed_latency_ms=9,
            )

    announcer = LazyAnnouncer()
    state.federation_announcer = announcer
    state.accept_federation_catalog({
        "bootstrap_server_id": "node-b",
        "peer": bootstrap_payload,
        "nodes": [_catalog_entry(third_payload)],
        "_roundtrip_ms": 7,
    })

    assert state.federation_registry.describe("node-c") is None
    assert state.federation_discovered_nodes()[0]["authenticated"] is False
    assert announcer.calls == []

    route = state.route_for(server_id="node-c", port=8141)

    assert route.server_id == "node-c"
    assert route.port == 8141
    assert route.latency_ms == 9
    assert announcer.calls == [(
        "node-c",
        "http://10.77.0.12:17998/api/federation/register",
    )]
