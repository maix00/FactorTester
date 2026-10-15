"""Peer Manager storage control uses server identity without a business port."""

import base64
from types import SimpleNamespace

from server.manager.http.federation import service_proxy
from server.manager.http.gateway import GatewayResponse


class _Handler(service_proxy.FederationServiceProxyRoutesMixin):
    def __init__(self, path, method, calls):
        self._payload = {
            "server_id": "storage-server", "port": 0,
            "path": path, "principal": "alice", "method": method,
            "body_b64": "",
        }
        self.state = SimpleNamespace(
            server_id="storage-server",
            _local_route=lambda **kwargs: SimpleNamespace(port=kwargs["port"]),
            route_request=lambda route, **kwargs: calls.append((route.port, kwargs))
            or GatewayResponse(200, b'{"success":true}', "application/json"),
        )

    def _has_federation_proxy_token(self):
        return True

    def _json_body(self, limit):
        return self._payload


def test_peer_storage_inventory_accepts_zero_port(monkeypatch):
    calls = []
    responses = []
    monkeypatch.setattr(service_proxy, "json_response",
                        lambda handler, payload, status=200: responses.append((payload, status)))
    _Handler("/api/jobs/storage?limit=1", "GET", calls)._federation_proxy()
    assert calls[0][0] == 0
    assert calls[0][1]["principal"] == "alice"
    assert base64.b64decode(responses[0][0]["body_b64"]) == b'{"success":true}'


def test_peer_rejects_unrelated_zero_port_route(monkeypatch):
    calls = []
    responses = []
    monkeypatch.setattr(service_proxy, "json_response",
                        lambda handler, payload, status=200: responses.append((payload, status)))
    _Handler("/api/jobs/job-1", "GET", calls)._federation_proxy()
    assert calls == []
    assert responses[0][1] == 400
