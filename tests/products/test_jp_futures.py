from __future__ import annotations

import settings

from sources.Tiger.data_source import TIGER
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


def test_tiger_declares_live_l2_instead_of_historical_bars():
    product = get_all_jp_futures()[0]

    assert TIGER.supports_product(product)
    assert not TIGER.has_available_data(product)
    assert [member.key for member in TIGER.members] == ["TigerOSEFuturesL2"]
    assert TIGER.members[0].dimensions == {
        "sampling_mode": "snapshot",
        "frequency": None,
        "data_kind": "order_book",
        "market_depth": "l2",
        "delivery_mode": "live_stream",
    }
    assert ("Tiger", "Tiger") not in (
        MarketDataModule.fields["data_source"].options
    )
    assert ("Local", "Local") in (
        MarketDataModule.fields["data_source"].options
    )
