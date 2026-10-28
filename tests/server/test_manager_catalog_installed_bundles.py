from types import SimpleNamespace

from server.manager.http import catalog_routes
from server.services import product_catalog_projection


def test_installed_bundles_route_is_metadata_only(monkeypatch):
    responses = []
    descriptor = {
        "id": "Local",
        "bundle_id": "Local",
        "members": [],
        "availability": {"status": "unknown", "product_count": None},
        "execution_location": "server",
    }
    client = {**descriptor, "id": "ClientOnly", "bundle_id": "ClientOnly",
              "execution_location": "client"}
    monkeypatch.setattr(
        product_catalog_projection, "installed_bundle_descriptors",
        lambda **kwargs: tuple(
            row for row in (descriptor, client)
            if kwargs.get("execution_location") in {None, row["execution_location"]}
        ),
    )
    monkeypatch.setattr(
        catalog_routes, "json_response",
        lambda _handler, value, status=200: responses.append((value, status)),
    )

    class Handler(catalog_routes.CatalogRoutesMixin):
        def _session(self):
            return {"username": "alice", "role": "user"}

        def _visitor_mode(self):
            return None

    handled = Handler()._serve_product_catalog(SimpleNamespace(
        path="/api/product-library/installed-bundles", query="",
    ))
    assert handled is True
    assert responses == [({
        "success": True,
        "origin": "server",
        "metadata_only": True,
        "sources": [descriptor],
    }, 200)]


def test_installed_bundles_route_rejects_visitor(monkeypatch):
    responses = []
    monkeypatch.setattr(
        catalog_routes, "json_response",
        lambda _handler, value, status=200: responses.append((value, status)),
    )

    class Visitor:
        principal = "guest"

    class Handler(catalog_routes.CatalogRoutesMixin):
        def _session(self):
            return None

        def _visitor_mode(self):
            return Visitor()

    handled = Handler()._serve_product_catalog(SimpleNamespace(
        path="/api/product-library/installed-bundles", query="",
    ))
    assert handled is True
    assert responses == [({
        "success": False,
        "error": "visitor cannot inspect installed bundles",
    }, 403)]


def test_installed_bundles_route_does_not_activate_sources(monkeypatch):
    import pytest
    from sources import registry

    responses = []
    monkeypatch.setattr(
        registry, "load_all_sources",
        lambda: pytest.fail("installed bundle metadata must not activate sources"),
    )
    monkeypatch.setattr(
        catalog_routes, "json_response",
        lambda _handler, value, status=200: responses.append((value, status)),
    )

    class Handler(catalog_routes.CatalogRoutesMixin):
        def _session(self):
            return {"username": "alice", "role": "user"}

        def _visitor_mode(self):
            return None

    assert Handler()._serve_product_catalog(SimpleNamespace(
        path="/api/product-library/installed-bundles", query="",
    )) is True
    assert responses[0][0]["metadata_only"] is True
