from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.data.types.data_money import DataMoney
from tools.products.Product import Product
from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.ledger import ledger_identity
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.cash_pool import set_cash_for_ledger_pool
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.margin_budget import MarginBudgetModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.strategy_book import strategy_book_store_for
from tools.testers.backtest.modules.target import TargetStrategyModule, TargetWeightIntent
from tools.testers.backtest.policies.margin_budget import default_margin_budget_policy


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def _context(strategies: set[Strategy]) -> FlowContext:
    return FlowContext(
        timestamp=pd.Timestamp("2025-01-02 09:00"),
        event_queue=EventQueue(),
        active_strategies=frozenset(strategies),
    )


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
    scaled_intent = ctx.get_for(TargetStrategyModule.trade_intent, strategy)
    assert type(scaled_intent) is TargetWeightIntent
    assert list(weights.values()) == pytest.approx([1.6] * 4)
    assert ctx.get(MarginBudgetModule.gross_leverage)["private:A1"] == pytest.approx(6.4)
    assert ctx.get(MarginBudgetModule.projected_margin)["private:A1"] == pytest.approx(80_000_000.0)


def test_mixed_margin_and_cash_products_use_one_for_cash_margin_rate() -> None:
    strategy = Strategy(alias="mixed")
    future, cash_product = _product(), _product()
    state = BacktestRunState(strategy_configs={strategy: StrategyConfig(strategy=strategy)})
    ledger = state.ledger_for_strategy(strategy)
    state.ledger_configs[ledger_identity("private:mixed")] = LedgerConfig(margin_mode="auto")
    set_cash_for_ledger_pool(state, ledger, DataMoney.from_major(
        1_000.0, currency="CNY", use_minor_units=False,
    ))
    ctx = _context({strategy})
    ctx.set_for(LedgerModule.equity, strategy, 1_000.0)
    ctx.set(MarketDataModule.current_prices, {future: 100.0, cash_product: 100.0})
    ctx.set_for(MarketDataModule.current_historical_fields, strategy, {
        future: {"LongMarginRatioByMoney": 0.10},
        cash_product: {},
    })
    intent = TargetWeightIntent({future: 0.5, cash_product: 0.5})
    ctx.set_for(TargetStrategyModule.trade_intent, strategy, intent)
    ctx.set_for(TargetStrategyModule.target_weights, strategy, intent.weights)

    MarginBudgetModule.apply_target_margin_budget.compute(state, ctx)

    summary = ctx.get(MarginBudgetModule.margin_budget_summary)["private:mixed"]
    assert summary["weighted_margin_ratio"] == pytest.approx(0.55)
    assert summary["gross_leverage"] == pytest.approx(0.30 / 0.55)
    assert summary["projected_margin"] == pytest.approx(300.0)


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


def test_margin_budget_pool_totals_do_not_depend_on_target_insertion_order(monkeypatch) -> None:
    import tools.testers.backtest.modules.margin_budget_impl.runtime as runtime

    def order_sensitive_sum(values) -> float:
        total = 0.0
        for value in values:
            total += float(value)
        return total

    monkeypatch.setattr(runtime, "sum", order_sensitive_sum, raising=False)
    products = [_product() for _ in range(4)]
    weights = [1e16, 1e15, 1.0, 1.0]

    def run(order: tuple[int, ...], alias: str) -> tuple[float, float]:
        strategy = Strategy(alias=alias)
        state = BacktestRunState(strategy_configs={
            strategy: StrategyConfig(strategy=strategy),
        })
        ledger = state.ledger_for_strategy(strategy)
        state.ledger_configs[ledger_identity(f"private:{alias}")] = LedgerConfig(
            margin_mode="fixed",
            fixed_margin_ratio=1.0,
        )
        set_cash_for_ledger_pool(
            state,
            ledger,
            DataMoney.from_major(1.0, currency="CNY", use_minor_units=False),
        )
        ctx = _context({strategy})
        ctx.set_for(LedgerModule.equity, strategy, 1.0)
        ctx.set(MarketDataModule.current_prices, {product: 1.0 for product in products})
        ctx.set_for(MarketDataModule.current_historical_fields, strategy, {
            product: {"VolumeMultiple": 1.0} for product in products
        })
        ordered_weights = {products[index]: weights[index] for index in order}
        intent = TargetWeightIntent(ordered_weights, reason="order_invariance")
        ctx.set_for(TargetStrategyModule.trade_intent, strategy, intent)
        ctx.set_for(TargetStrategyModule.target_weights, strategy, intent.weights)
        captured: list[tuple[float, float]] = []

        def policy(request):
            captured.append((request.raw_gross_notional, request.raw_projected_margin))
            return default_margin_budget_policy(request)

        strategy_book_store_for(state).policies.margin_budget = policy
        MarginBudgetModule.apply_target_margin_budget.compute(state, ctx)

        return captured[0]

    forward = run((2, 0, 1, 3), "forward")
    small_first = run((1, 2, 3, 0), "small-first")

    assert forward == small_first
