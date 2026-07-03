from __future__ import annotations

from dataclasses import dataclass

from sources.LocalCNFutures.clearing_rules import register_local_cnfutures_exchange_rules
from tools.traderules import (
    ExchangeClearingRule,
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
        )
    )

    product = _ProductLike("FOO.XTEST")

    assert exchange_rule_defaults_for_product(product, ("MoneyCalculationPolicy",)) == {
        "MoneyCalculationPolicy": "per_contract_price_point"
    }


def test_local_cnfutures_declares_exchange_clearing_rule_defaults() -> None:
    register_local_cnfutures_exchange_rules()

    assert exchange_rule_defaults_for_product(_ProductLike("AP.CZC"), ("MoneyCalculationPolicy",)) == {
        "MoneyCalculationPolicy": "aggregate"
    }
    assert exchange_rule_defaults_for_product(_ProductLike("RU.SHF"), ("MoneyCalculationPolicy",)) == {
        "MoneyCalculationPolicy": "aggregate"
    }
