"""One-scheduler bootstrap and direct-registration behavior."""

from __future__ import annotations

import json
from urllib.error import URLError

import pytest

from server.manager.domain.federation import FederationAnnouncer


class _Response:
    def __init__(self, value: dict[str, object]) -> None:
        self.body = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.body


class _Transport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.bootstrap_available = True
        self.direct_server_id = "node-c"

    def open(self, request, *, timeout: float):
        del timeout
        url = request.full_url
        payload = json.loads(request.data.decode("utf-8"))
        self.calls.append((url, payload))
        if url.startswith("http://10.77.0.2"):
            if not self.bootstrap_available:
                raise URLError("bootstrap offline")
            return _Response({"kind": "bootstrap"})
        return _Response({
            "kind": "direct",
            "bootstrap_server_id": self.direct_server_id,
            "peer": {"server_id": self.direct_server_id},
        })


def test_discovered_node_is_authenticated_lazily_then_renewed() -> None:
    transport = _Transport()
    payload_number = 0

    def payload_factory() -> dict[str, object]:
        nonlocal payload_number
        payload_number += 1
        return {"heartbeat": payload_number}

    def response_handler(value: dict[str, object]):
        return value["kind"]

    announcer = FederationAnnouncer(
        bootstrap_url="http://10.77.0.2:17998/api/federation/register",
        registration_token="cluster-token",
        payload_factory=payload_factory,
        response_handler=response_handler,
        transport=transport,
    )

    announcer.run_once()
    assert [url for url, _payload in transport.calls] == [
        "http://10.77.0.2:17998/api/federation/register",
    ]

    announcer.activate(
        "node-c",
        "http://10.77.0.12:17998/api/federation/register",
    )
    transport.bootstrap_available = False
    announcer.run_once()

    assert [url for url, _payload in transport.calls] == [
        "http://10.77.0.2:17998/api/federation/register",
        "http://10.77.0.12:17998/api/federation/register",
        "http://10.77.0.2:17998/api/federation/register",
        "http://10.77.0.12:17998/api/federation/register",
    ]
    assert transport.calls[0][1] == {"heartbeat": 1}
    assert transport.calls[1][1] == {"heartbeat": 2}
    assert transport.calls[2][1] == transport.calls[3][1] == {"heartbeat": 3}
    assert announcer.active_registration_urls == (
        "http://10.77.0.12:17998/api/federation/register",
    )


def test_lazy_activation_rejects_a_different_responder_identity() -> None:
    transport = _Transport()
    transport.direct_server_id = "node-x"
    handled: list[dict[str, object]] = []
    announcer = FederationAnnouncer(
        bootstrap_url="http://10.77.0.2:17998/api/federation/register",
        registration_token="cluster-token",
        payload_factory=lambda: {"heartbeat": 1},
        response_handler=handled.append,
        transport=transport,
    )

    with pytest.raises(ValueError, match="does not match discovered node"):
        announcer.activate(
            "node-c",
            "http://10.77.0.12:17998/api/federation/register",
        )

    assert handled == []
    assert announcer.active_registration_urls == ()


def test_temporary_host_address_failure_does_not_kill_heartbeat_scheduler():
    """A real scheduler iteration must recover, without publishing stale endpoints."""
    transport = _Transport()
    attempts = 0
    def payload_factory():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError('current host LAN address is unavailable')
        return {'heartbeat': attempts}
    announcer = FederationAnnouncer(
        bootstrap_url='http://10.77.0.2:17998/api/federation/register',
        registration_token='cluster-token', payload_factory=payload_factory,
        transport=transport,
    )
    class TwoIterations:
        def is_set(self):
            return attempts >= 2
        def wait(self, _interval):
            return False
    announcer._stop = TwoIterations()
    announcer._run()
    assert attempts == 2
    assert [payload for _, payload in transport.calls] == [{'heartbeat': 2}]
