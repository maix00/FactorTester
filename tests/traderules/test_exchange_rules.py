from __future__ import annotations

from dataclasses import dataclass

from sources.LocalCNFutures.clearing_rules import register_local_cnfutures_exchange_rules
from tools.traderules import (
    ExchangeClearingRule,
    exchange_rule_manifest_for_product,
    exchange_rule_defaults_for_product,
    register_exchange_clearing_rule,
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
