from __future__ import annotations

from server.manager.services.client_product_catalog import ClientProductCatalogMixin


class _Catalog(ClientProductCatalogMixin):
    account_domain_sync = object()

    def __init__(self) -> None:
        self.reads: list[dict] = []

    def _account_catalog_entities(self, principal: str, **options):
        self.reads.append({"principal": principal, **options})
        return [{
            "payload": {
                "id": "shared-group",
                "name": "Shared",
                "paths": ["Product/A", "Product/B"],
                "category_ids": ["metals"],
            },
            "deleted": False,
        }]


def test_product_group_summary_carries_bounded_scope_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        "server.services.product_catalog_projection.source_ids_by_product_path",
        lambda paths: {
            "Product/A": ("source-a",),
            "Product/B": ("source-a", "source-b"),
        },
    )
    catalog = _Catalog()

    rows = catalog.product_group_summaries("alice")

    assert catalog.reads == [{
        "principal": "alice",
        "entity_type": "product_group",
        "include_shared": True,
        "include_deleted": True,
    }]
    assert rows[0]["category_ids"] == ["metals"]
    assert rows[0]["path_sources"] == [
        {"source_ids": ["source-a"]},
        {"source_ids": ["source-a", "source-b"]},
    ]
    assert "paths" not in rows[0]
    assert "products" not in rows[0]
