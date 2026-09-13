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
        self.items = []

    def public_data(self, _route, **kwargs):
        self.calls += 1
        if self.fail:
            raise ConnectionError("peer is offline")
        if kwargs.get("operation") == "profile-conversation-items":
            return {
                "items": list(self.items),
                "has_more": False,
                "after": None,
                "turn_count": 1,
            }
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


def test_remote_conversation_content_is_never_served_from_stale_cache():
    route = ServiceRoute(
        server_id="remote-main",
        role="manager",
        branch="main",
        revision="rev-1",
        port=7998,
    )
    registry = _Registry(route)
    gateway = _Gateway()
    gateway.items = [{
        "id": "assistant-1",
        "type": "assistant_message",
        "content": [{"type": "output_text", "text": "latest"}],
    }]
    service = _service(registry, gateway)

    assert service.profile_conversation_items(
        "remote-main", "GTHT@parent@1", "GTHT@child@2", "maxc", "c-1",
    )["items"] == gateway.items

    gateway.fail = True
    try:
        service.profile_conversation_items(
            "remote-main", "GTHT@parent@1", "GTHT@child@2", "maxc", "c-1",
        )
    except ConnectionError as error:
        assert "offline" in str(error)
    else:  # pragma: no cover - stale content must never masquerade as current
        raise AssertionError("stale conversation content was returned")


def test_restored_publication_refreshes_stale_storage_source_once():
    route = ServiceRoute(server_id="remote-main", role="manager", branch="main", revision="new", port=7998)
    service = _service(_Registry(route), _Gateway())
    service._publication_sources["publication"] = "retired-manager"
    calls = []
    def refresh(viewer):
        calls.append(viewer)
        service._publication_sources["publication"] = "remote-main"
        return []
    service.list_visible = refresh
    assert service._publication_route("publication", "viewer") == route
    assert calls == ["viewer"]


def test_report_branches_merge_transports_but_not_other_owners():
    from types import SimpleNamespace
    from server.manager.http.research_catalog_routes import ResearchCatalogRoutesMixin
    owner = "owner"
    publications = [
        {"report_id":"r", "owner_ref":owner, "branch_ref":"main", "publication_id":"pub-main"},
        {"report_id":"r", "owner_ref":"other", "branch_ref":"secret", "publication_id":"other-pub"},
    ]
    handler = SimpleNamespace(_research_service=lambda:SimpleNamespace(list_visible=lambda _:publications))
    report = {"report_id":"r", "owner_ref":owner, "branches":[
        {"branch_ref":"main", "publication_id":"server:self:package:main"},
        {"branch_ref":"experiment", "publication_id":"server:self:package:experiment"},
    ]}
    result = ResearchCatalogRoutesMixin._research_catalog_publication_branches(handler,[report],owner)
    assert [b["branch_ref"] for b in result[0]["branches"]] == ["main", "experiment"]
    assert result[0]["branches"][0]["publication_id"] == "pub-main"


def test_missing_report_route_activates_only_exact_discovered_source():
    route = ServiceRoute(server_id='remote-main', role='manager', branch='main', revision='one', port=7998)
    registry = _Registry(route)
    registry.routes = lambda **kwargs: []
    service = _service(registry, _Gateway())
    service._publication_sources['report'] = 'remote-main'
    service.list_visible = lambda viewer: []
    calls = []
    def activate(source):
        calls.append(source)
        registry.routes = lambda **kwargs: [route]
    service.activate_source = activate
    assert service._publication_route('report', 'alice') == route
    assert calls == ['remote-main']
    assert service._publication_route('report', 'alice') == route
    assert calls == ['remote-main']
    assert service._publication_route('unknown-report', 'alice') is None
    assert calls == ['remote-main']
