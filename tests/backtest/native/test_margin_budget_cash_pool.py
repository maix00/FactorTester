from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.data.types.data_money import DataMoney
from tools.products.Product import Product
from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.ledger import LedgerState, ledger_identity
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.cash_pool import set_cash_for_ledger_pool
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.margin_budget import MarginBudgetModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.strategy_book import strategy_book_store_for
from tools.testers.backtest.modules.target import TargetStrategyModule, TargetWeightIntent


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def test_shared_cash_pool_gets_one_combined_eighty_percent_budget() -> None:
    a, b = Strategy(alias="A"), Strategy(alias="B")
    pa, pb = _product(), _product()
    ledger_a = LedgerState(strategy=a, base_currency="CNY", ledger_id="book-a")
    ledger_b = LedgerState(strategy=b, base_currency="CNY", ledger_id="book-b")
    state = BacktestRunState(
        ledgers={"book-a": ledger_a, "book-b": ledger_b},
        strategy_configs={a: StrategyConfig(strategy=a), b: StrategyConfig(strategy=b)},
    )
    store = strategy_book_store_for(state)
    store.register_strategy_ledgers(
        a, ("book-a",), default_ledger_id="book-a",
        cash_pool_ids_by_ledger={"book-a": "pool"},
    )
    store.register_strategy_ledgers(
        b, ("book-b",), default_ledger_id="book-b",
        cash_pool_ids_by_ledger={"book-b": "pool"},
    )
    for ledger_id in ("book-a", "book-b"):
        state.ledger_configs[ledger_identity(ledger_id)] = LedgerConfig(
            margin_mode="fixed", fixed_margin_ratio=0.10,
        )
    set_cash_for_ledger_pool(state, ledger_a, DataMoney.from_major(
        100_000_000.0, currency="CNY", use_minor_units=True,
    ))
    ctx = FlowContext(
        timestamp=pd.Timestamp("2025-01-02"), event_queue=EventQueue(),
        active_strategies=frozenset({a, b}),
    )
    ctx.set(MarketDataModule.current_prices, {pa: 100.0, pb: 100.0})
    for strategy, product in ((a, pa), (b, pb)):
        ctx.set_for(LedgerModule.equity, strategy, 100_000_000.0)
        ctx.set_for(MarketDataModule.current_historical_fields, strategy, {
            product: {"VolumeMultiple": 10.0},
        })
        ctx.set_for(TargetStrategyModule.trade_intent, strategy, TargetWeightIntent({product: 1.0}))
        ctx.set_for(TargetStrategyModule.target_weights, strategy, {product: 1.0})

    MarginBudgetModule.apply_target_margin_budget.compute(state, ctx)

    combined_gross = sum(
        abs(next(iter(ctx.get_for(TargetStrategyModule.target_weights, strategy).values())))
        for strategy in (a, b)
    )
    assert combined_gross == pytest.approx(8.0)
    assert ctx.get(MarginBudgetModule.projected_margin)["pool"] == pytest.approx(80_000_000.0)
