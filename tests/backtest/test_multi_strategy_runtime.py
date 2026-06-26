from __future__ import annotations

import numpy as np
import pandas as pd

from tools.testers.backtest.engines.factors.events import PrecomputedFactorPublisher
from tools.testers.backtest.engines.native.runtime import (
    EventRuntime,
    EventTopic,
    MarketSliceBarrier,
    ProductPrice,
    ReplayEventSource,
)
from tools.testers.backtest.engines.execution.trading import (
    CashAccounting,
    ImmediateBroker,
    Ledger,
    MarketState,
    OrderManager,
)
from tools.testers.backtest.engines.strategies.signal import SignalStrategy


def test_multiple_strategies_share_data_and_factor_but_not_portfolios() -> None:
    timestamp = pd.Timestamp("2026-01-01 09:01")
    runtime = EventRuntime("multi-strategy-run")
    runtime.add_source(ReplayEventSource(
        [timestamp, timestamp],
        [ProductPrice("A", 100.0), ProductPrice("B", 200.0)],
    ))
    market = MarketState()
    barrier = MarketSliceBarrier(["A", "B"])
    factor = PrecomputedFactorPublisher(
        "factor-combination-1",
        pd.DataFrame([[0.8, -0.2]], index=[timestamp], columns=["A", "B"]),
    )

    long_group = SignalStrategy(
        "combination-1:group-5",
        "portfolio-long",
        "factor-combination-1",
        ("A", "B"),
        lambda signal: np.array([1.0, 0.0]),
    )
    short_group = SignalStrategy(
        "combination-1:group-1",
        "portfolio-short",
        "factor-combination-1",
        ("A", "B"),
        lambda signal: np.array([0.0, 1.0]),
    )
    long_ledger = Ledger(
        "portfolio-long", ("A", "B"), 1_000_000, CashAccounting()
    )
    short_ledger = Ledger(
        "portfolio-short", ("A", "B"), 1_000_000, CashAccounting()
    )
    broker = ImmediateBroker(market)

    runtime.subscribe(EventTopic.MARKET_DATA, market.on_market_data)
    runtime.subscribe(EventTopic.MARKET_DATA, barrier.on_price)
    runtime.subscribe(EventTopic.MARKET_SLICE_CLOSED, factor.on_market_slice)
    runtime.subscribe(EventTopic.FACTOR_SIGNAL, long_group.on_factor_signal)
    runtime.subscribe(EventTopic.FACTOR_SIGNAL, short_group.on_factor_signal)
    runtime.subscribe(
        EventTopic.PORTFOLIO_INTENT,
        OrderManager(long_ledger).on_portfolio_intent,
    )
    runtime.subscribe(
        EventTopic.PORTFOLIO_INTENT,
        OrderManager(short_ledger).on_portfolio_intent,
    )
    runtime.subscribe(EventTopic.ORDER_SUBMITTED, broker.on_order_submitted)
    runtime.subscribe(EventTopic.FILL, long_ledger.on_fill)
    runtime.subscribe(EventTopic.FILL, short_ledger.on_fill)
    runtime.run()

    assert long_ledger.positions == {"A": 1.0, "B": 0.0}
    assert short_ledger.positions == {"A": 0.0, "B": 1.0}
    assert long_ledger.cash_minor == 990_000
    assert short_ledger.cash_minor == 980_000
    fills = [record.event.payload for record in runtime.journal if record.event.topic == EventTopic.FILL]
    assert {fill.strategy_id for fill in fills} == {
        "combination-1:group-5",
        "combination-1:group-1",
    }
