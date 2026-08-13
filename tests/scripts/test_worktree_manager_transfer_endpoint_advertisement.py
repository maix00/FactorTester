from __future__ import annotations

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

    try:
        receiver.accept_transfer_node_advertisement(advertised, now=102.0)
    except ValueError as exc:
        assert "peer" in str(exc).lower() or "wireguard" in str(exc).lower()
    else:  # pragma: no cover - security invariant
        raise AssertionError("public peer endpoint was accepted")


def test_federation_registration_payload_includes_transfer_node(tmp_path) -> None:
    source = _state(tmp_path, "node-a")
    source.configure_transfer_endpoints(server_endpoints(
        client_control_endpoint="https://198.51.100.10:7998",
        client_data_endpoint="https://198.51.100.10:7997",
        peer_host="10.77.0.10",
    ), now=100.0)

    payload = source.registration_payload(
        "https://198.51.100.10:7998",
        artifact_endpoint="https://198.51.100.10:7997",
    )

    assert payload["transfer_node"]["node_id"] == "node-a"
    assert payload["transfer_node"]["peer_control_endpoint"] == (
        "http://10.77.0.10:17998"
    )
