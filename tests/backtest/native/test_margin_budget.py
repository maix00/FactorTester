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
from tools.testers.backtest.policies.margin_budget import MarginBudgetRequest, default_margin_budget_policy


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def _context(strategies: set[Strategy]) -> FlowContext:
    return FlowContext(
        timestamp=pd.Timestamp("2025-01-02 09:00"),
        event_queue=EventQueue(),
        active_strategies=frozenset(strategies),
    )


def test_default_margin_budget_reports_six_point_four_gross_leverage() -> None:
    request = MarginBudgetRequest(
        cash_pool_id="P", effective_timestamp=pd.Timestamp("2025-01-02"),
        equity=100_000_000.0, target_utilization=0.80, max_utilization=0.85,
        tolerance=0.01, raw_gross_notional=100_000_000.0,
        raw_projected_margin=12_500_000.0,
    )

    decision = default_margin_budget_policy(request)

    assert decision.scale == pytest.approx(6.4)
    assert decision.gross_leverage == pytest.approx(6.4)
    assert decision.projected_utilization == pytest.approx(0.80)


def test_margin_budget_scales_equal_notional_targets_and_publishes_step_fields() -> None:
    strategy = Strategy(alias="A1")
    products = [_product() for _ in range(4)]
    config = StrategyConfig(strategy=strategy, field_values={
        MarginBudgetModule.target_margin_utilization: 0.80,
        MarginBudgetModule.max_margin_utilization: 0.85,
    })
    state = BacktestRunState(strategy_configs={strategy: config})
    ledger = state.ledger_for_strategy(strategy)
    state.ledger_configs[ledger_identity("private:A1")] = LedgerConfig(
        margin_mode="fixed", fixed_margin_ratio=0.125,
    )
    set_cash_for_ledger_pool(state, ledger, DataMoney.from_major(
        100_000_000.0, currency="CNY", use_minor_units=True,
    ))
    ctx = _context({strategy})
    ctx.set_for(LedgerModule.equity, strategy, 100_000_000.0)
    ctx.set(MarketDataModule.current_prices, {product: 100.0 for product in products})
    ctx.set_for(MarketDataModule.current_historical_fields, strategy, {
        product: {"VolumeMultiple": 10.0} for product in products
    })
    intent = TargetWeightIntent({product: 0.25 for product in products}, reason="group_membership")
    ctx.set_for(TargetStrategyModule.trade_intent, strategy, intent)
    ctx.set_for(TargetStrategyModule.target_weights, strategy, intent.weights)

    MarginBudgetModule.apply_target_margin_budget.compute(state, ctx)

    weights = ctx.get_for(TargetStrategyModule.target_weights, strategy)
    assert list(weights.values()) == pytest.approx([1.6] * 4)
    assert ctx.get(MarginBudgetModule.gross_leverage)["private:A1"] == pytest.approx(6.4)
    assert ctx.get(MarginBudgetModule.projected_margin)["private:A1"] == pytest.approx(80_000_000.0)


def test_shared_cash_pool_gets_one_combined_eighty_percent_budget() -> None:
    a, b = Strategy(alias="A"), Strategy(alias="B")
    pa, pb = _product(), _product()
    config_a = StrategyConfig(strategy=a)
    config_b = StrategyConfig(strategy=b)
    ledger = LedgerState(strategy=a, base_currency="CNY", ledger_id="shared")
    state = BacktestRunState(
        ledgers={"shared": ledger}, strategy_configs={a: config_a, b: config_b},
    )
    store = strategy_book_store_for(state)
    store.register_strategy_ledgers(a, ("shared",), default_ledger_id="shared", cash_pool_ids_by_ledger={"shared": "pool"})
    store.register_strategy_ledgers(b, ("shared",), default_ledger_id="shared", cash_pool_ids_by_ledger={"shared": "pool"})
    state.ledger_configs[ledger_identity("shared")] = LedgerConfig(
        margin_mode="fixed", fixed_margin_ratio=0.10,
    )
    set_cash_for_ledger_pool(state, ledger, DataMoney.from_major(
        100_000_000.0, currency="CNY", use_minor_units=True,
    ))
    ctx = _context({a, b})
    ctx.set(MarketDataModule.current_prices, {pa: 100.0, pb: 100.0})
    for strategy, product in ((a, pa), (b, pb)):
        ctx.set_for(LedgerModule.equity, strategy, 100_000_000.0)
        ctx.set_for(MarketDataModule.current_historical_fields, strategy, {product: {"VolumeMultiple": 10.0}})
        ctx.set_for(TargetStrategyModule.trade_intent, strategy, TargetWeightIntent({product: 1.0}))
        ctx.set_for(TargetStrategyModule.target_weights, strategy, {product: 1.0})

    MarginBudgetModule.apply_target_margin_budget.compute(state, ctx)

    combined_gross = sum(
        abs(next(iter(ctx.get_for(TargetStrategyModule.target_weights, strategy).values())))
        for strategy in (a, b)
    )
    assert combined_gross == pytest.approx(8.0)
    assert ctx.get(MarginBudgetModule.projected_margin)["pool"] == pytest.approx(80_000_000.0)


def test_disabled_margin_keeps_cash_target_weight() -> None:
    strategy = Strategy(alias="cash")
    product = _product()
    state = BacktestRunState(strategy_configs={strategy: StrategyConfig(strategy=strategy)})
    ledger = state.ledger_for_strategy(strategy)
    state.ledger_configs[ledger_identity("private:cash")] = LedgerConfig(margin_mode="none")
    set_cash_for_ledger_pool(state, ledger, DataMoney.from_major(
        1_000.0, currency="CNY", use_minor_units=True,
    ))
    ctx = _context({strategy})
    ctx.set_for(LedgerModule.equity, strategy, 1_000.0)
    ctx.set(MarketDataModule.current_prices, {product: 10.0})
    ctx.set_for(TargetStrategyModule.trade_intent, strategy, TargetWeightIntent({product: 1.0}))
    ctx.set_for(TargetStrategyModule.target_weights, strategy, {product: 1.0})

    MarginBudgetModule.apply_target_margin_budget.compute(state, ctx)

    assert ctx.get_for(TargetStrategyModule.target_weights, strategy) == {product: 1.0}
    assert ctx.get(MarginBudgetModule.gross_leverage) == {}
