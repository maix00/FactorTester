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
