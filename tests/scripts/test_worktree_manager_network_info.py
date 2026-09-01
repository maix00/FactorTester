"""Focused federation behavior tests."""

from __future__ import annotations

from server.manager import runtime as manager
from server.manager.domain.federation import registry as registry_module
from server.manager.services.network_info import local_internal_addresses
from tests.federation_fixtures import federation_registration as _registration


def test_public_device_targets_are_server_discovered_https_peers(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_LAN_ADDRESSES", "192.168.50.10")
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
    assert [item["server_id"] for item in info["online_public_server_targets"]] == [
        "public-near",
        "public-far",
    ]


def test_internal_targets_expose_their_managed_organization_scope(tmp_path) -> None:
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_role="main",
        server_id="public-main",
        state_root=tmp_path / "manager-state",
    )
    state.public_server = True
    internal = _registration("internal-gtht", latency_ms=4, load=0)
    internal.update({
        "role": "feat",
        "public_server": False,
        "managed_organizations": ["GTHT"],
        "internal_addresses": ["192.168.50.10"],
    })
    state.federation_registry.register(internal)

    targets = state.server_network_info()["internal_server_targets"]

    assert targets == [{
        "server_id": "internal-gtht",
        "role": "feat",
        "addresses": ["192.168.50.10"],
        "manager_port": 7998,
        "managed_organizations": ["GTHT"],
        "online": True,
    }]


def test_expired_internal_server_is_not_in_network_information(
    tmp_path,
    monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_role="main",
        server_id="public-main",
        state_root=tmp_path / "manager-state",
    )
    state.public_server = True
    internal = _registration("internal-gtht", latency_ms=4, load=0)
    internal.update({
        "role": "feat",
        "public_server": False,
        "internal_addresses": ["192.168.50.10"],
    })
    monkeypatch.setattr(registry_module.time, "time", lambda: 100.0)
    state.federation_registry.register(internal)
    monkeypatch.setattr(registry_module.time, "time", lambda: 1000.0)

    info = state.server_network_info()

    assert info["internal_server_targets"] == []
    assert info["internal_server_addresses"] == []


def test_lan_addresses_exclude_loopback_and_local_only_values() -> None:
    assert local_internal_addresses(configured=[
        "127.0.0.1",
        "0.0.0.0",
        "169.254.1.5",
        "192.168.50.10",
        "192.168.50.10",
    ]) == ["192.168.50.10"]


def test_fresh_host_snapshot_replaces_hostname_discovery(
    tmp_path,
    monkeypatch,
) -> None:
    snapshot = tmp_path / "host-lan-addresses.json"
    snapshot.write_text(
        '{"schema_version": 1, "observed_at": 100, '
        '"addresses": ["192.168.50.10"]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("FACTORTESTER_LAN_ADDRESS_STATE_FILE", str(snapshot))

    assert local_internal_addresses(
        hostnames=["container-hostname"],
        now=110,
    ) == ["192.168.50.10"]


def test_stale_or_missing_host_snapshot_never_reuses_an_old_address(
    tmp_path,
    monkeypatch,
) -> None:
    snapshot = tmp_path / "host-lan-addresses.json"
    snapshot.write_text(
        '{"schema_version": 1, "observed_at": 100, '
        '"addresses": ["192.168.50.10"]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("FACTORTESTER_LAN_ADDRESS_STATE_FILE", str(snapshot))
    monkeypatch.setenv("FACTORTESTER_LAN_ADDRESS_MAX_AGE_SECONDS", "20")

    assert local_internal_addresses(now=121) == []
    snapshot.unlink()
    assert local_internal_addresses(now=122) == []


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
