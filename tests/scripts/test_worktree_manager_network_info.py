"""Focused federation behavior tests."""

from __future__ import annotations

from server.manager import runtime as manager
from server.manager.services.network_info import local_internal_addresses
from tests.federation_fixtures import federation_registration as _registration

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

