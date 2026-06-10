from tools.products.Futures import Futures, FuturesContract
from tools.products.Product import Product


def test_product_defaults_to_non_margin_traded():
    product = Product("SPOT.TEST", _local_only=True)

    assert product.is_margin_traded is False


def test_futures_are_margin_traded():
    future = Futures("IF.CFE", _local_only=True)
    contract = FuturesContract("IF2406.CFE", _local_only=True)

    assert future.is_margin_traded is True
    assert contract.is_margin_traded is True


def test_product_can_hardcode_trading_spec_fields():
    product = Product(
        "STOCK.TEST",
        _local_only=True,
        multiplier=1,
        min_tick=0.01,
        min_trade_quantity=100,
        open_ratio=0.0003,
    )

    assert product.get_multiplier() == 1
    assert product.get_min_tick() == 0.01
    assert product.get_min_trade_quantity() == 100
    assert product.get_open_ratio() == 0.0003
