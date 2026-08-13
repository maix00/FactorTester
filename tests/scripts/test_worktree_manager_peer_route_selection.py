from __future__ import annotations

from email.message import Message
from io import BytesIO

import pytest

from server.manager.domain.federation import (
    FederatedGateway,
    FederatedServerRegistry,
)


class _Response:
    status = 200
    headers = Message()

    def __init__(self, body: bytes) -> None:
        self._body = BytesIO(body)

    def read(self, maximum: int = -1) -> bytes:
        return self._body.read(maximum)

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


class _Transport:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def open(self, request, *, timeout: float):
        self.urls.append(request.full_url)
        return _Response(b'{"success":true,"ports":[]}')


def _registration(*, peer: bool = True) -> dict[str, object]:
    value: dict[str, object] = {
        "server_id": "node-a",
        "role": "main",
        "endpoint": "https://198.51.100.10:7998",
        "proxy_token": "secret",
        "ports": [{"port": 8000, "online": True}],
    }
    if peer:
        value["transfer_node"] = {
            "schema_version": 1,
            "node_id": "node-a",
            "identity": {
                "node_id": "node-a",
                "algorithm": "Ed25519",
                "public_key": "not-used-by-routing",
                "fingerprint": "not-used-by-routing",
            },
            "client_control_endpoint": "https://198.51.100.10:7998",
            "client_data_endpoint": "https://198.51.100.10:7997",
            "peer_control_endpoint": "http://10.77.0.10:17998",
            "peer_data_endpoint": "http://10.77.0.10:17997",
            "lease_seconds": 30,
        }
    return value


def test_machine_gateway_uses_peer_control_not_public_client_endpoint(
    tmp_path,
) -> None:
    registry = FederatedServerRegistry(tmp_path / "registry.json")
    registry.register(_registration())
    route = registry.routes(include_offline=True)[0]
    transport = _Transport()

    value = FederatedGateway(transport=transport).capabilities(route)

    assert value["success"] is True
    assert route.endpoint == "https://198.51.100.10:7998"
    assert route.peer_control_endpoint == "http://10.77.0.10:17998"
    assert transport.urls == [
        "http://10.77.0.10:17998/api/federation/capabilities"
    ]


def test_machine_gateway_never_falls_back_to_public_endpoint(tmp_path) -> None:
    registry = FederatedServerRegistry(tmp_path / "registry.json")
    registry.register(_registration(peer=False))
    route = registry.routes(include_offline=True)[0]

    with pytest.raises(ConnectionError, match="peer control"):
        FederatedGateway(transport=_Transport()).capabilities(route)
