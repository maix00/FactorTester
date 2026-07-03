from __future__ import annotations

from dataclasses import dataclass

from sources.LocalCNFutures.clearing_rules import register_local_cnfutures_exchange_rules
from tools.traderules import (
    ExchangeClearingRule,
    ExchangeTradingRule,
    exchange_order_constraints_for_snapshot,
    exchange_rule_manifest_for_product,
    exchange_rule_defaults_for_product,
    exchange_tradable_status_for_snapshot,
    exchange_trading_rule_for_product,
    exchange_trading_rule_manifest_for_product,
    register_exchange_clearing_rule,
    register_exchange_trading_rule,
)


@dataclass(frozen=True)
class _ProductLike:
    name: str
    exchange_id: str | None = None


def test_exchange_rule_defaults_can_be_registered_by_data_source() -> None:
    register_exchange_clearing_rule(
        ExchangeClearingRule(
            exchange_id="XTEST",
            fields={"MoneyCalculationPolicy": "per_contract_price_point", "Ignored": 1},
            provider="test",
            label="测试交易所规则",
            note="测试规则说明",
            field_labels={"MoneyCalculationPolicy": "金额计算口径"},
            field_notes={"MoneyCalculationPolicy": "逐合约点值口径"},
        )
    )

    product = _ProductLike("FOO.XTEST")

    assert exchange_rule_defaults_for_product(product, ("MoneyCalculationPolicy",)) == {
        "MoneyCalculationPolicy": "per_contract_price_point"
    }
    manifest = exchange_rule_manifest_for_product(product, ("MoneyCalculationPolicy",))
    assert manifest is not None
    assert manifest["label"] == "测试交易所规则"
    assert manifest["note"] == "测试规则说明"
    assert manifest["fields"] == [{
        "key": "MoneyCalculationPolicy",
        "value": "per_contract_price_point",
        "label": "金额计算口径",
        "note": "逐合约点值口径",
    }]


def test_local_cnfutures_declares_exchange_clearing_rule_defaults() -> None:
    register_local_cnfutures_exchange_rules()

    assert exchange_rule_defaults_for_product(_ProductLike("AP.CZC"), ("MoneyCalculationPolicy",)) == {
        "MoneyCalculationPolicy": "aggregate"
    }
    assert exchange_rule_defaults_for_product(
        _ProductLike("AP.CZC"),
        ("CostBasisMethod", "MoneyCalculationPolicy"),
    ) == {
        "CostBasisMethod": "DailyMarkToMarket",
        "MoneyCalculationPolicy": "aggregate",
    }
    assert exchange_rule_defaults_for_product(_ProductLike("RU.SHF"), ("MoneyCalculationPolicy",)) == {
        "MoneyCalculationPolicy": "aggregate"
    }


def test_exchange_trading_rule_can_infer_tradable_status_from_snapshot() -> None:
    register_exchange_trading_rule(
        ExchangeTradingRule(
            exchange_id="XTRD",
            tradability_policy="valid_close_and_positive_volume",
            provider="test",
            label="测试交易规则",
            note="需要有效价格和成交量",
        )
    )
    tradable = _ProductLike("A.XTRD")
    halted = _ProductLike("B.XTRD")

    status = exchange_tradable_status_for_snapshot({
        "close": {tradable: 10.0, halted: 10.0},
        "volume": {tradable: 1.0, halted: 0.0},
    })

    assert status == {tradable: True, halted: False}
    manifest = exchange_trading_rule_manifest_for_product(tradable)
    assert manifest is not None
    assert manifest["label"] == "测试交易规则"
    assert manifest["tradability_policy"] == "valid_close_and_positive_volume"


def test_local_cnfutures_declares_exchange_trading_rule_defaults() -> None:
    register_local_cnfutures_exchange_rules()
    product = _ProductLike("AP.CZC")

    rule = exchange_trading_rule_for_product(product)
    assert rule is not None
    assert rule.tradability_policy == "valid_close_and_price_limits"

    status = exchange_tradable_status_for_snapshot({"close": {product: 10.0}})
    assert status == {product: True}


def test_price_limit_policy_is_side_aware() -> None:
    register_exchange_trading_rule(
        ExchangeTradingRule(
            exchange_id="XLIM",
            tradability_policy="valid_close_and_price_limits",
        )
    )
    upper_locked = _ProductLike("UP.XLIM")
    lower_locked = _ProductLike("DN.XLIM")
    normal = _ProductLike("OK.XLIM")

    constraints = exchange_order_constraints_for_snapshot({
        "close": {upper_locked: 10.0, lower_locked: 8.0, normal: 9.0},
        "upper_limit": {upper_locked: 10.0, lower_locked: 10.0, normal: 10.0},
        "lower_limit": {upper_locked: 8.0, lower_locked: 8.0, normal: 8.0},
    })

    assert constraints[upper_locked].tradable is True
    assert constraints[upper_locked].can_buy is False
    assert constraints[upper_locked].can_sell is True
    assert constraints[lower_locked].can_buy is True
    assert constraints[lower_locked].can_sell is False
    assert constraints[normal].can_buy is True
    assert constraints[normal].can_sell is True
