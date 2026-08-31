from __future__ import annotations

from types import SimpleNamespace

from server.manager.http import catalog_routes


def test_legacy_catalog_product_routes_are_not_handled() -> None:
    class Handler(catalog_routes.CatalogRoutesMixin):
        pass

    handler = Handler()
    assert handler._serve_product_catalog(SimpleNamespace(
        path="/api/catalog/product-groups",
    )) is False
    assert handler._serve_product_catalog_write(SimpleNamespace(
        path="/api/catalog/product-groups",
    )) is False


def test_manager_product_group_put_uses_module_unquote_without_crashing(monkeypatch) -> None:
    responses: list[tuple[dict, int]] = []
    updates: list[tuple] = []

    class ClientState:
        def update_product_group(self, *args):
            updates.append(args)
            return {
                "group_ref": "product-group:pg_day",
                "name": "CNFuturesDay",
                "paths": ["Product/Futures/CNFutures/_products/AP.CZC"],
                "category_ids": ["cnfutures_day_night"],
            }

    class Handler(catalog_routes.CatalogRoutesMixin):
        command = "PUT"
        state = SimpleNamespace(client_state=ClientState())

        def _session(self):
            return {"username": "alice", "role": "user"}

        def _visitor_mode(self):
            return None

        def _json_body(self, _limit):
            return {
                "name": "CNFuturesDay",
                "paths": ["Product/Futures/CNFutures/_products/AP.CZC"],
                "category_ids": ["cnfutures_day_night"],
            }

    monkeypatch.setattr(
        catalog_routes,
        "json_response",
        lambda _handler, value, status=200: responses.append((value, status)),
    )

    handled = Handler()._serve_product_catalog_write(SimpleNamespace(
        path="/api/product-library/product-groups/product-group%3Apg_day",
    ))

    assert handled is True
    assert updates == [(
        "alice",
        "product-group:pg_day",
        "CNFuturesDay",
        ["Product/Futures/CNFutures/_products/AP.CZC"],
        ["cnfutures_day_night"],
    )]
    assert responses == [({
        "success": True,
        "origin": "server",
        "group": {
            "group_ref": "product-group:pg_day",
            "name": "CNFuturesDay",
            "paths": ["Product/Futures/CNFutures/_products/AP.CZC"],
            "category_ids": ["cnfutures_day_night"],
        },
    }, 200)]
