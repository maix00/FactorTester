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
