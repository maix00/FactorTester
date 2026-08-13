from __future__ import annotations

import pytest

from server.manager.network_endpoints import (
    client_endpoint_for_port,
    peer_bind_address,
    server_endpoints,
)


@pytest.mark.parametrize("value", ["", "0.0.0.0", "::", "127.0.0.1", "8.8.8.8"])
def test_peer_listener_rejects_missing_wildcard_loopback_or_public_bind(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="WireGuard|private"):
        peer_bind_address(value)


def test_public_and_peer_endpoints_are_independently_configured() -> None:
    endpoints = server_endpoints(
        client_control_endpoint="https://203.0.113.10:7998",
        client_data_endpoint="https://203.0.113.10:7997",
        peer_host="10.77.0.2",
    )

    assert endpoints.client_control_endpoint.endswith(":7998")
    assert endpoints.client_data_endpoint.endswith(":7997")
    assert endpoints.peer_control_endpoint == "http://10.77.0.2:17998"
    assert endpoints.peer_data_endpoint == "http://10.77.0.2:17997"


def test_public_data_endpoint_derives_only_from_public_control_host() -> None:
    assert client_endpoint_for_port(
        "https://203.0.113.10:7998", 7997,
    ) == "https://203.0.113.10:7997"
    assert client_endpoint_for_port(
        "http://[fd00::2]:7998", 7997,
    ) == "http://[fd00::2]:7997"
