from __future__ import annotations

import settings

from sources.Tiger.data_source import (
    TIGER,
    TIGER_OSE_DAY1,
    TIGER_OSE_MIN1,
    tiger_cache_path,
)
from sources.Tiger.products import JPFutures, get_all_jp_futures
from tools.testers.backtest.modules.market_data import MarketDataModule


def test_ose_futures_are_first_class_products_without_network_discovery():
    products = get_all_jp_futures()

    assert [product.name for product in products] == [
        "JNI.OSE",
        "JMI.OSE",
        "JTM.OSE",
        "JTI.OSE",
        "NK225MC.OSE",
    ]
    assert all(isinstance(product, JPFutures) for product in products)
    assert products[0].currency == "JPY"
    assert products[0].timezone == "Asia/Tokyo"
    assert products[0].tiger_identifier == "JNImain"
    assert products[0].get_multiplier() == 1000.0
    assert products[0].get_min_tick() == 10.0
    assert products[1].tiger_identifier == "JMImain"
    assert products[1].get_multiplier() == 100.0
    assert products[1].get_min_tick() == 5.0

    registered_names = {
        product.name for product in settings.get_all_products()
    }
    assert {
        "JNI.OSE",
        "JMI.OSE",
        "JTM.OSE",
        "JTI.OSE",
        "NK225MC.OSE",
    } <= registered_names


def test_tiger_historical_bundle_is_file_backed_and_never_network_falls_back(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("FACTORTESTER_TIGER_CACHE_DIR", str(tmp_path))
    product = get_all_jp_futures()[0]

    assert TIGER.members == (TIGER_OSE_MIN1, TIGER_OSE_DAY1)
    assert tiger_cache_path(product, "1min") == str(
        tmp_path / "OSE" / "MIN1" / "JNImain.parquet"
    )
    assert tiger_cache_path(product, "1day") == str(
        tmp_path / "OSE" / "DAY1" / "JNImain.parquet"
    )
    assert product not in TIGER_OSE_MIN1
    assert product not in TIGER_OSE_DAY1
    assert ("Tiger", "Tiger") in MarketDataModule.fields["data_source"].options
