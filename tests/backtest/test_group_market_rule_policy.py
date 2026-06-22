from types import SimpleNamespace

import pandas as pd
import pytest

from tools.factors.tests.single_factor_test.group.core import _resolve_group_trade_specs


def _product():
    return SimpleNamespace(
        name="TEST.1",
        point_value=10.0,
        multiplier=10.0,
        min_tick=0.2,
        min_trade_quantity=1.0,
        long_margin_ratio=0.12,
        is_margin_traded=True,
    )


def test_latest_market_rule_fallback_is_counted_as_approximation(monkeypatch) -> None:
    monkeypatch.setattr(
        "sources.OpenCTP.fields.get_products_specs_over_date_range",
        lambda **kwargs: {},
    )
    product = _product()
    bundle = _resolve_group_trade_specs(
        signal_valid_cols=[product],
        valid_cols=[product],
        fee=0.0,
        index_list=pd.date_range("2024-01-01", periods=2),
        market_rule_fallback="latest_available",
    )

    assert bundle.rule_provenance["multiplier"] == {
        "effective_at": 0,
        "as_of_latest": 2,
        "configured_default": 0,
    }


def test_strict_market_rule_policy_names_missing_field_and_product(monkeypatch) -> None:
    monkeypatch.setattr(
        "sources.OpenCTP.fields.get_products_specs_over_date_range",
        lambda **kwargs: {},
    )
    product = _product()
    with pytest.raises(ValueError, match="field=open_ratio, product=TEST.1"):
        _resolve_group_trade_specs(
            signal_valid_cols=[product],
            valid_cols=[product],
            fee=0.0,
            index_list=pd.date_range("2024-01-01", periods=2),
            market_rule_fallback="strict_historical",
        )
