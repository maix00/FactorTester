from types import SimpleNamespace

import pytest

from tools.data.types import DataCurrency, CurrencyConversionContext, require_product_currency_vector


def test_data_currency_normalizes_code():
    currency = DataCurrency("usd")

    assert currency.code == "USD"
    assert str(currency) == "USD"


def test_currency_context_allows_single_currency_without_fx_data():
    ctx = CurrencyConversionContext(base_currency="USD")

    assert float(ctx.to_base(12.34, "USD")) == 12.34


def test_currency_context_requires_explicit_base_currency():
    with pytest.raises(ValueError, match="需要显式指定 base_currency"):
        CurrencyConversionContext()


def test_currency_context_raises_when_cross_currency_fx_is_missing():
    ctx = CurrencyConversionContext(base_currency="CNY")

    with pytest.raises(ValueError, match="Missing FX rate USD->CNY"):
        ctx.to_base(12.34, "USD")


def test_currency_context_raises_when_currency_is_missing():
    ctx = CurrencyConversionContext(base_currency="CNY")

    with pytest.raises(ValueError, match="缺少交易品种 currency"):
        ctx.to_base(12.34, None)


def test_product_currency_vector_does_not_fallback_to_base_currency():
    products = [SimpleNamespace(name="P0", currency=None)]

    with pytest.raises(ValueError, match="产品缺少 currency 字段"):
        require_product_currency_vector(products)

    with pytest.raises(ValueError, match="产品缺少 currency 字段"):
        require_product_currency_vector(products, explicit=[" "])


def test_currency_context_applies_conversion_fee_when_fx_exists():
    ctx = CurrencyConversionContext(
        base_currency="CNY",
        conversion_fee_rate=0.01,
        rate_provider=lambda from_currency, to_currency, time_key: 7.0,
    )

    assert float(ctx.to_base(10.0, "USD", applies_fee=True)) == 70.7
