from __future__ import annotations

from server.manager.domain.federation import ServiceRoute
from server.manager.services.federated_public_data import (
    FederatedPublicDataService,
)


class _Registry:
    def __init__(self, route):
        self.route = route

    def routes(self, *, include_offline=False):
        return [self.route] if self.route.online or include_offline else []


class _Gateway:
    def __init__(self):
        self.fail = False
        self.calls = 0
        self.rows = []

    def public_data(self, _route, **_kwargs):
        self.calls += 1
        if self.fail:
            raise ConnectionError("peer is offline")
        return {"conversations": list(self.rows)}


def _service(registry, gateway):
    return FederatedPublicDataService(
        server_id="local-1",
        registry=registry,
        gateway=gateway,
        public_research=object(),
        client_state=object(),
    )


def test_remote_history_queries_source_before_using_request_cache():
    route = ServiceRoute(
        server_id="remote-main",
        role="manager",
        branch="main",
        revision="rev-1",
        port=7998,
    )
    registry = _Registry(route)
    gateway = _Gateway()
    gateway.rows = [{"conversation_id": "c-1", "updated_at": 1}]
    service = _service(registry, gateway)

    first = service.profile_conversations(
        "remote-main", "GTHT@parent@1", "GTHT@child@2", "maxc",
    )
    gateway.rows = [{"conversation_id": "c-1", "updated_at": 2}]
    second = service.profile_conversations(
        "remote-main", "GTHT@parent@1", "GTHT@child@2", "maxc",
    )

    assert first[0]["updated_at"] == 1
    assert second[0]["updated_at"] == 2
    assert gateway.calls == 2


def test_remote_history_uses_bounded_request_cache_only_when_source_fails():
    route = ServiceRoute(
        server_id="remote-main",
        role="manager",
        branch="main",
        revision="rev-1",
        port=7998,
    )
    registry = _Registry(route)
    gateway = _Gateway()
    gateway.rows = [{"conversation_id": "c-1", "updated_at": 1}]
    service = _service(registry, gateway)

    expected = service.profile_conversations(
        "remote-main", "GTHT@parent@1", "GTHT@child@2", "maxc",
    )
    gateway.fail = True
    actual = service.profile_conversations(
        "remote-main", "GTHT@parent@1", "GTHT@child@2", "maxc",
    )

    assert actual == expected
    assert gateway.calls == 2
