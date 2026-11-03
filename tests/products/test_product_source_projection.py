from __future__ import annotations

from server.services.product_catalog_projection import (
    product_source_descriptors,
    source_family_ids_for_member_ids,
)
from server.modules.shared.price_services import cached_contracts


def test_contract_source_member_projects_contract_catalog_and_data() -> None:
    descriptor = next(
        item for item in product_source_descriptors() if item["id"] == "Local"
    )
    member = next(
        item for item in descriptor["members"]
        if item["id"] == "LocalCNFuturesContractMIN1"
    )

    assert member["catalog_product_count"] == len(cached_contracts())
    assert member["product_count"] == len(cached_contracts())
    assert member["product_paths"] == [
        "Product/FuturesContract/CNFuturesContract",
    ]
    assert member["availability"]["status"] == "ready"
    assert member["naming_scheme"] == "local_cnfutures_contract_uid_v1"
    assert member["nautilus_capability"]["adapter_available"] is True
    assert member["nautilus_capability"]["supported_book_types"] == ["L1_MBP"]
    assert member["nautilus_capability"]["instrument_scope"] == "physical_contract"
    assert "local_cnfutures_contract_uid_v1" in descriptor["naming_schemes"]
    assert descriptor["product_paths"] == [
        "Product/Futures/CNFutures",
        "Product/FuturesContract/CNFuturesContract",
    ]


def test_concrete_source_members_resolve_to_source_families() -> None:
    descriptors = ({
        "id": "Local",
        "family_id": "Local",
        "members": [{"id": "LocalCNFuturesContractMIN1"}],
    }, {
        "id": "Remote",
        "members": [{"id": "RemoteCNFuturesDAY1"}],
    })

    assert source_family_ids_for_member_ids(
        ["LocalCNFuturesContractMIN1", "RemoteCNFuturesDAY1", "missing"],
        descriptors,
    ) == ("Local", "Remote", "missing")


def test_real_local_contract_tree_pages_preserve_refs_and_source_bindings(monkeypatch):
    """Use the isolated real catalog fixture, never a running Manager/database."""
    from server.manager.services.client_product_catalog import ClientProductCatalogMixin
    from server.modules.shared import price_services
    from server.services.product_catalog_projection import clear_product_catalog_projection_cache
    from tools.products.classifier_paths import classifier_object_path
    import pytest
    contracts = cached_contracts()
    if len(contracts) > 10_000:
        pytest.skip("real metadata fixture exceeds this bounded acceptance budget")
    clear_product_catalog_projection_cache()
    calls = []
    original = price_services.available_sources_for_product
    def sources(product, freq=None):
        calls.append(product.name)
        return original(product, freq)
    monkeypatch.setattr(price_services, "available_sources_for_product", sources)
    refs = set()
    page = 1
    while True:
        result = ClientProductCatalogMixin.contract_tree_page(
            "Product/FuturesContract/CNFuturesContract/_products", source_ids=("Local",),
            page=page, limit=100,
        )
        for row in result["nodes"]:
            assert row["source_family_ids"] == ["Local"]
            assert "LocalCNFuturesContractMIN1" in row["source_ids"]
            assert row["key"] not in refs
            refs.add(row["key"])
        if not result["has_more"]:
            break
        page += 1
    assert refs == {classifier_object_path(item) for item in contracts}
    assert len(calls) == len(refs)
    search = ClientProductCatalogMixin.contract_tree_page(
        "Product/FuturesContract/CNFuturesContract/_products", source_ids=("Local",),
        query="LocalCNFuturesContractMIN1", limit=100,
    )
    assert search["total"] == len(refs)
    assert len(calls) == len(refs)
    print(f"real-contract-metadata refs={len(refs)} pages={page} warm-source-projections=0")
    clear_product_catalog_projection_cache()
