"""Focused federation behavior tests."""

from __future__ import annotations

import time
import pytest
from server.manager import runtime as manager
from server.manager.domain.federation import (
    FederationConfigStore,
    FederatedServerRegistry,
    ServiceRoute,
    TargetUnavailable,
)
from tests.federation_fixtures import federation_registration as _registration

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

