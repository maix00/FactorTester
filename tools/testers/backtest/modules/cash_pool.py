"""CashPoolModule — owns cash-pool balances and future FX movements.

StrategyBook declares which Ledger belongs to which cash pool; this module
stores the money. A private cash account is represented the same way as a
shared account: a cash pool that happens to contain one ledger. Cross-currency
movement must be represented as explicit FX trade events, not by sharing one
cash pool across currencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef


@dataclass
class CashPoolStore:
    cash_by_pool: dict[str, Any] = field(default_factory=dict)


class CashPoolModule(ExecutableModule):
    key: ClassVar[str] = "cash_pool"
    label: ClassVar[str] = "现金池"
    order: ClassVar[int] = 158

    cash: ClassVar[FieldRef[Any]] = FieldRef("cash")
    initial_capital_major: ClassVar[FieldRef[float]] = FieldRef("initial_capital_major")
    base_currency: ClassVar[FieldRef[str]] = FieldRef("base_currency")
    currency_conversion_fee_rate: ClassVar[FieldRef[float]] = FieldRef("currency_conversion_fee_rate")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "initial_capital_major": FieldDefinition(
            public=True, label="初始资金", control_template="number", default=100_000_000.0, tab="capital",
            chip_template="初始资金: {value}", tab_label="资金", tab_order=50,
        ),
        "base_currency": FieldDefinition(
            public=True, label="币种", control_template="select", default="CNY", tab="capital",
            chip_template="币种: {value}", tab_label="资金", tab_order=50,
        ),
        "currency_conversion_fee_rate": FieldDefinition(
            public=True, label="换汇费率", control_template="number", default=0.0, tab="capital",
            minimum=0.0, step=0.000001,
            chip_template="换汇费率: {value}", tab_label="资金", tab_order=50,
        ),
    }


def cash_pool_store_for(state: object) -> CashPoolStore:
    store = getattr(state, "cash_pool_store", None)
    if store is None:
        store = CashPoolStore()
        setattr(state, "cash_pool_store", store)
    return store


def cash_for_ledger(state: object, ledger_state: object):
    from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

    store = cash_pool_store_for(state)
    pool_id = cash_pool_id_for_ledger(state, ledger_state)
    return store.cash_by_pool.get(pool_id)


def set_cash_for_ledger_pool(state: object, ledger_state: object, cash: object) -> None:
    from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

    cash_pool_store_for(state).cash_by_pool[cash_pool_id_for_ledger(state, ledger_state)] = cash
