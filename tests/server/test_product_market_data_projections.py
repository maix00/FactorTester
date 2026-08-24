from __future__ import annotations

import pandas as pd

from server.modules.shared.price_data_helpers import open_interest_column
from server.services.product_market_data.products import _price_rows
from server.services.product_market_data.sampling import bounded_ohlcv_rows
from tools.data.types import DataFreq


def test_open_interest_column_accepts_canonical_and_provider_aliases() -> None:
    assert open_interest_column(["OPEN", "OPEN_INTEREST", "CLOSE"]) == "OPEN_INTEREST"
    assert open_interest_column(["open_price", "open_interest", "close_price"]) == "open_interest"
    assert open_interest_column(["open", "OI", "close"]) == "OI"
    assert open_interest_column(["open", "hold", "close"]) == "hold"
    assert open_interest_column(["open", "close"]) is None


def test_product_price_rows_keeps_open_interest_from_provider_alias() -> None:
    frame = pd.DataFrame(
        {
            "OPEN": [10.0, 11.0],
            "HIGH": [12.0, 13.0],
            "LOW": [9.0, 10.0],
            "CLOSE": [11.0, 12.0],
            "VOLUME": [100, 120],
            "OI": [80, 90],
        },
        index=pd.date_range("2025-01-02", periods=2, freq="D"),
    )

    rows, has_open_interest = _price_rows(
        object(), frame, adjusted=False, frequency=DataFreq.DAY1,
    )

    assert has_open_interest is True
    assert [row["open_interest"] for row in rows] == [80.0, 90.0]


def test_product_chart_sampling_preserves_ohlcv_bucket_semantics() -> None:
    rows = [{
        "timestamp": index, "open": index + 1, "high": index + 3,
        "low": index, "close": index + 2, "volume": 10,
        "open_interest": 100 + index,
    } for index in range(200)]

    sampled, total = bounded_ohlcv_rows(rows, {"max_points": 100})

    assert total == 200
    assert len(sampled) == 100
    assert sampled[0] == {
        **rows[1], "open": 1, "high": 4, "low": 0,
        "close": 3, "volume": 20, "open_interest": 101,
    }


def test_manager_product_fields_resolves_contracts_for_independent_detail_tabs(
    monkeypatch,
) -> None:
    from server.manager.services.client_state import ClientStateService
    from server.modules.shared import price_services
    from server.services import product_catalog_projection

    class Parent:
        name = "A.DCE"

    class Contract:
        name = "DCE|A|2501"
        parent_product = Parent()

    monkeypatch.setattr(price_services, "cached_products", lambda: ())
    monkeypatch.setattr(
        price_services, "find_contract_product", lambda value: Contract(),
    )
    monkeypatch.setattr(
        price_services, "find_product", lambda products, value: None,
    )
    monkeypatch.setattr(
        price_services, "product_public_fields",
        lambda value: {"contract_uid": {"value": value.name}},
    )
    monkeypatch.setattr(
        product_catalog_projection,
        "catalog_product_records",
        lambda: ({
            "name": "A.DCE",
            "source_ids": ["PublicSource"],
            "available_source_ids": ["PublicSource"],
        },),
    )
    monkeypatch.setattr(
        product_catalog_projection,
        "catalog_product_description",
        lambda product, name: "A产品",
    )

    value = ClientStateService.product_fields("DCE|A|2501")

    assert value["product_type"] == "contract"
    assert value["name"] == "DCE|A|2501"
    assert value["parent_product"] == "A.DCE"
    assert value["source_ids"] == ["PublicSource"]
    assert value["fields"]["contract_uid"]["value"] == "DCE|A|2501"
