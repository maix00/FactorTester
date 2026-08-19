from __future__ import annotations

import json
import time

import pytest

from server.manager import runtime as manager
from server.manager.network_endpoints import server_endpoints


def _state(tmp_path, node_id: str):
    root = tmp_path / node_id
    root.mkdir()
    return manager.ManagerState(
        root,
        "python",
        state_root=root / "state",
        server_id=node_id,
    )


def test_authenticated_registration_preserves_distinct_client_and_peer_endpoints(
    tmp_path,
) -> None:
    source = _state(tmp_path, "node-a")
    receiver = _state(tmp_path, "node-b")
    source.configure_transfer_endpoints(server_endpoints(
        client_control_endpoint="https://198.51.100.10:7998",
        client_data_endpoint="https://198.51.100.10:7997",
        peer_host="10.77.0.10",
    ), now=100.0)

    advertised = source.transfer_node_advertisement(now=101.0)
    receiver.accept_transfer_node_advertisement(advertised, now=102.0)

    assert advertised["schema_version"] == 2
    assert isinstance(advertised["signature"], str)
    assert advertised["signature"]
    assert "private_key" not in repr(advertised)
    stored = receiver.transfer_endpoints.require("node-a", now=103.0)
    assert stored.peer_control_endpoint == "http://10.77.0.10:17998"
    assert stored.peer_data_endpoint == "http://10.77.0.10:17997"
    assert "198.51.100.10" not in repr(stored)
    assert receiver.node_identities.require("node-a").fingerprint == (
        advertised["identity"]["fingerprint"]
    )


def test_registration_rejects_public_address_disguised_as_peer_endpoint(
    tmp_path,
) -> None:
    receiver = _state(tmp_path, "node-b")
    source = _state(tmp_path, "node-a")
    source.configure_transfer_endpoints(server_endpoints(
        client_control_endpoint="https://198.51.100.10:7998",
        client_data_endpoint="https://198.51.100.10:7997",
        peer_host="10.77.0.10",
    ), now=100.0)
    advertised = source.transfer_node_advertisement(now=101.0)
    advertised["peer_data_endpoint"] = "http://8.8.8.8:17997"

    with pytest.raises(PermissionError, match="signature"):
        receiver.accept_transfer_node_advertisement(advertised, now=102.0)


def test_registration_rejects_replayed_advertisement(tmp_path) -> None:
    receiver = _state(tmp_path, "node-b")
    source = _state(tmp_path, "node-a")
    source.configure_transfer_endpoints(server_endpoints(
        client_control_endpoint="https://198.51.100.10:7998",
        client_data_endpoint="https://198.51.100.10:7997",
        peer_host="10.77.0.10",
    ), now=100.0)
    advertised = source.transfer_node_advertisement(now=101.0)

    receiver.accept_transfer_node_advertisement(advertised, now=102.0)

    with pytest.raises(PermissionError, match="replayed"):
        receiver.accept_transfer_node_advertisement(advertised, now=103.0)


def test_registration_rejects_expired_advertisement(tmp_path) -> None:
    receiver = _state(tmp_path, "node-b")
    source = _state(tmp_path, "node-a")
    source.configure_transfer_endpoints(server_endpoints(
        client_control_endpoint="https://198.51.100.10:7998",
        client_data_endpoint="https://198.51.100.10:7997",
        peer_host="10.77.0.10",
    ), now=100.0)
    advertised = source.transfer_node_advertisement(ttl=5.0, now=101.0)

    with pytest.raises(PermissionError, match="expired"):
        receiver.accept_transfer_node_advertisement(advertised, now=106.0)


def test_registration_rejects_delayed_older_advertisement(tmp_path) -> None:
    receiver = _state(tmp_path, "node-b")
    source = _state(tmp_path, "node-a")
    source.configure_transfer_endpoints(server_endpoints(
        client_control_endpoint="https://198.51.100.10:7998",
        client_data_endpoint="https://198.51.100.10:7997",
        peer_host="10.77.0.10",
    ), now=100.0)
    older = source.transfer_node_advertisement(now=101.0)
    newer = source.transfer_node_advertisement(now=102.0)

    receiver.accept_transfer_node_advertisement(newer, now=103.0)

    with pytest.raises(PermissionError, match="stale"):
        receiver.accept_transfer_node_advertisement(older, now=104.0)


def test_registration_accepts_fresh_heartbeat_after_previous_lease_expires(
    tmp_path,
) -> None:
    receiver = _state(tmp_path, "node-b")
    source = _state(tmp_path, "node-a")
    source.configure_transfer_endpoints(server_endpoints(
        client_control_endpoint="https://198.51.100.10:7998",
        client_data_endpoint="https://198.51.100.10:7997",
        peer_host="10.77.0.10",
    ), now=100.0)
    previous = source.transfer_node_advertisement(ttl=5.0, now=101.0)
    receiver.accept_transfer_node_advertisement(previous, now=102.0)

    fresh = source.transfer_node_advertisement(ttl=5.0, now=106.0)
    stored = receiver.accept_transfer_node_advertisement(fresh, now=106.5)

    assert stored.online is True
    assert stored.expires_at == 111.0


def test_registration_heartbeats_remain_ordered_at_same_clock_tick(
    tmp_path,
) -> None:
    receiver = _state(tmp_path, "node-b")
    source = _state(tmp_path, "node-a")
    source.configure_transfer_endpoints(server_endpoints(
        client_control_endpoint="https://198.51.100.10:7998",
        client_data_endpoint="https://198.51.100.10:7997",
        peer_host="10.77.0.10",
    ), now=100.0)

    first = source.transfer_node_advertisement(now=101.0)
    second = source.transfer_node_advertisement(now=101.0)
    receiver.accept_transfer_node_advertisement(first, now=101.5)
    receiver.accept_transfer_node_advertisement(second, now=101.5)

    assert second["issued_at"] > first["issued_at"]


def test_registration_clock_remains_ordered_after_node_restart(tmp_path) -> None:
    root = tmp_path / "node-a"
    root.mkdir()
    source = manager.ManagerState(
        root,
        "python",
        state_root=root / "state",
        server_id="node-a",
    )
    endpoints = server_endpoints(
        client_control_endpoint="https://198.51.100.10:7998",
        client_data_endpoint="https://198.51.100.10:7997",
        peer_host="10.77.0.10",
    )
    source.configure_transfer_endpoints(endpoints, now=100.0)
    before_restart = source.transfer_node_advertisement(now=101.0)

    restarted = manager.ManagerState(
        root,
        "python",
        state_root=root / "state",
        server_id="node-a",
    )
    restarted.configure_transfer_endpoints(endpoints, now=99.0)
    after_restart = restarted.transfer_node_advertisement(now=100.0)

    assert after_restart["issued_at"] > before_restart["issued_at"]


def test_federation_registration_payload_includes_transfer_node(tmp_path) -> None:
    source = _state(tmp_path, "node-a")
    source.configure_transfer_endpoints(server_endpoints(
        client_control_endpoint="https://198.51.100.10:7998",
        client_data_endpoint="https://198.51.100.10:7997",
        peer_host="10.77.0.10",
    ), now=100.0)

    payload = source.registration_payload("https://198.51.100.10:7998")

    assert payload["transfer_node"]["node_id"] == "node-a"
    assert payload["transfer_node"]["peer_control_endpoint"] == (
        "http://10.77.0.10:17998"
    )
    assert "latency_ms" not in payload


def test_internal_registration_uses_fresh_host_address_snapshot(
    tmp_path,
    monkeypatch,
) -> None:
    snapshot = tmp_path / "host-lan-addresses.json"
    snapshot.write_text(json.dumps({
        "schema_version": 1,
        "observed_at": time.time(),
        "addresses": ["10.98.186.177"],
    }), encoding="utf-8")
    monkeypatch.setenv("FACTORTESTER_LAN_ADDRESS_STATE_FILE", str(snapshot))
    source = _state(tmp_path, "node-a")
    source.configure_transfer_endpoints(server_endpoints(
        client_control_endpoint="http://10.98.181.217:7998",
        client_data_endpoint="http://10.98.181.217:7997",
        peer_host="10.77.0.10",
    ), now=100.0)

    payload = source.registration_payload("http://10.98.181.217:7998")

    assert payload["internal_addresses"] == ["10.98.186.177"]
    assert payload["endpoint"] == "http://10.98.186.177:7998"
    assert payload["transfer_node"]["client_control_endpoint"] == (
        "http://10.98.186.177:7998"
    )
    assert payload["transfer_node"]["client_data_endpoint"] == (
        "http://10.98.186.177:7997"
    )


def test_internal_registration_stops_when_host_snapshot_is_stale(
    tmp_path,
    monkeypatch,
) -> None:
    snapshot = tmp_path / "host-lan-addresses.json"
    snapshot.write_text(json.dumps({
        "schema_version": 1,
        "observed_at": 1,
        "addresses": ["10.98.181.217"],
    }), encoding="utf-8")
    monkeypatch.setenv("FACTORTESTER_LAN_ADDRESS_STATE_FILE", str(snapshot))
    source = _state(tmp_path, "node-a")
    source.configure_transfer_endpoints(server_endpoints(
        client_control_endpoint="http://127.0.0.1:7998",
        client_data_endpoint="http://127.0.0.1:7997",
        peer_host="10.77.0.10",
    ), now=100.0)

    with pytest.raises(ValueError, match="LAN address is unavailable"):
        source.registration_payload("http://127.0.0.1:7998")
