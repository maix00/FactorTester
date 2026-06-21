from __future__ import annotations

import numpy as np
import pandas as pd

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr import ColumnRef, EvaluateContext

from tools.backtest.event_driven.backtest import BacktestRunner, ExecutionVenue, StrategyLane
from tools.backtest.event_driven.contracts import BacktestPlan, RunIdentity
from tools.backtest.factors.incremental import (
    compile_incremental_factor,
    compile_streaming_factor,
)
from tools.backtest.event_driven.runtime import MarketSlice, ProductPrice, ReplayEventSource
from tools.backtest.execution.trading import (
    CashAccounting,
    ImmediateBroker,
    Ledger,
    MarketState,
    OrderManager,
)
from tools.backtest.strategies.signal import SignalStrategy


def test_same_factor_expr_matches_batch_and_streaming_execution() -> None:
    index = pd.date_range("2026-01-01 09:01", periods=5, freq="min")
    products = ("A", "B")
    values = pd.DataFrame(
        {"A": [1.0, 2.0, 3.0, 4.0, 5.0], "B": [5.0, 4.0, np.nan, 2.0, 1.0]},
        index=index,
    )
    expression = (ColumnRef(DataColumn.CLOSE) * 2.0).rolling_mean(3)
    preloaded = {
        (product, DataFreq.MIN1.name): pd.DataFrame(
            {DataColumn.CLOSE.name: values[product]}, index=index
        )
        for product in products
    }
    batch = expression.evaluate(ctx=EvaluateContext(
        products, DataFreq.MIN1, preloaded=preloaded
    ))

    plan = compile_streaming_factor(expression, products)
    streamed_rows = []
    for timestamp, row in values.iterrows():
        market = MarketSlice({
            product: ProductPrice(
                product,
                price=float(row[product]) if pd.notna(row[product]) else 1.0,
                fields={DataColumn.CLOSE.name: float(row[product])},
            )
            for product in products
        })
        streamed_rows.append(plan.update(timestamp, market))
    streamed = pd.DataFrame(streamed_rows, index=index)

    pd.testing.assert_frame_equal(streamed, batch)


def test_runner_calculates_factor_incrementally_without_precomputed_values() -> None:
    index = pd.date_range("2026-01-01 09:01", periods=2, freq="min")
    products = ("A",)
    expression = ColumnRef(DataColumn.CLOSE)
    factor = compile_incremental_factor("live-close", expression, products)
    market = MarketState()
    broker = ImmediateBroker(market)
    strategy = SignalStrategy(
        "incremental-strategy",
        "incremental-portfolio",
        products,
        lambda signal: np.array([signal.values["A"]]),
    )
    ledger = Ledger(
        strategy.portfolio_id,
        products,
        initial_cash_minor=100_000,
        accounting=CashAccounting(),
    )
    source = ReplayEventSource(
        index,
        [
            ProductPrice("A", 10.0, {DataColumn.CLOSE.name: 1.0}),
            ProductPrice("A", 10.0, {DataColumn.CLOSE.name: 2.0}),
        ],
    )
    runner = BacktestRunner(
        BacktestPlan(RunIdentity("incremental-run"), index, products),
        market_source=source,
        market=market,
        factors=(factor,),
        lanes=(StrategyLane(strategy, ledger, OrderManager(ledger)),),
        venues=(ExecutionVenue(broker.on_order_submitted),),
    )

    result = runner.run()

    portfolio = result.portfolios[strategy.portfolio_id]
    assert portfolio.final_snapshot.positions == {"A": 2.0}
    assert [fill.quantity for fill in portfolio.fills] == [1.0, 1.0]
    assert len(portfolio.snapshots) == 2


def test_shift_rolling_and_cross_sectional_ops_match_batch_backend() -> None:
    index = pd.date_range("2026-01-01 09:01", periods=4, freq="min")
    products = ("A", "B")
    values = pd.DataFrame(
        {"A": [1.0, 2.0, 4.0, 8.0], "B": [4.0, 3.0, 2.0, 1.0]},
        index=index,
    )
    close = ColumnRef(DataColumn.CLOSE)
    expression = (close.shift(1) + close.rolling_std(3)).cs_rank()
    preloaded = {
        (product, DataFreq.MIN1.name): pd.DataFrame(
            {DataColumn.CLOSE.name: values[product]}, index=index
        )
        for product in products
    }
    batch = expression.evaluate(ctx=EvaluateContext(
        products, DataFreq.MIN1, preloaded=preloaded
    ))
    plan = compile_streaming_factor(expression, products)

    streamed = pd.DataFrame([
        plan.update(timestamp, MarketSlice({
            product: ProductPrice(
                product,
                price=float(row[product]),
                fields={DataColumn.CLOSE.name: float(row[product])},
            )
            for product in products
        }))
        for timestamp, row in values.iterrows()
    ], index=index)

    pd.testing.assert_frame_equal(streamed, batch)
