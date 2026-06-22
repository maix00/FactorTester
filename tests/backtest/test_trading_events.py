from __future__ import annotations

import numpy as np
import pandas as pd

from tools.backtest.factors.events import PrecomputedFactorPublisher
from tools.backtest.event_driven.runtime import (
    EventRuntime,
    EventTopic,
    MarketSliceBarrier,
    ProductPrice,
    ReplayEventSource,
)
from tools.backtest.execution.trading import (
    CashAccounting,
    ImmediateBroker,
    Ledger,
    MarketState,
    OrderManager,
)
from tools.backtest.strategies.signal import SignalStrategy


def test_market_to_factor_to_order_to_fill_to_ledger() -> None:
    timestamp = pd.Timestamp("2026-01-01 09:01")
    runtime = EventRuntime("vertical-run")
    runtime.add_source(ReplayEventSource(
        [timestamp, timestamp],
        [ProductPrice("A", 100.0), ProductPrice("B", 200.0)],
    ))

    market = MarketState()
    barrier = MarketSliceBarrier(["A", "B"])
    factor = PrecomputedFactorPublisher(
        "momentum",
        pd.DataFrame([[0.8, -0.2]], index=[timestamp], columns=["A", "B"]),
    )
    strategy = SignalStrategy(
        "strategy-1",
        "portfolio-1",
        "momentum",
        ("A", "B"),
        lambda signal: np.array([2.0, 0.0]),
    )
    ledger = Ledger(
        "portfolio-1",
        ("A", "B"),
        initial_cash_minor=1_000_000,
        accounting=CashAccounting(),
    )
    orders = OrderManager(ledger)
    broker = ImmediateBroker(market)

    runtime.subscribe(EventTopic.MARKET_DATA, market.on_market_data)
    runtime.subscribe(EventTopic.MARKET_DATA, barrier.on_price)
    runtime.subscribe(EventTopic.MARKET_SLICE_CLOSED, factor.on_market_slice)
    runtime.subscribe(EventTopic.FACTOR_SIGNAL, strategy.on_factor_signal)
    runtime.subscribe(EventTopic.PORTFOLIO_INTENT, orders.on_portfolio_intent)
    runtime.subscribe(EventTopic.ORDER_SUBMITTED, broker.on_order_submitted)
    runtime.subscribe(EventTopic.FILL, ledger.on_fill)
    runtime.run()

    assert ledger.positions == {"A": 2.0, "B": 0.0}
    assert ledger.cash_minor == 980_000
    assert len(ledger.fills) == 1
    assert [record.event.topic for record in runtime.journal][-5:] == [
        EventTopic.FACTOR_SIGNAL,
        EventTopic.PORTFOLIO_INTENT,
        EventTopic.ORDER_SUBMITTED,
        EventTopic.ORDER_ACCEPTED,
        EventTopic.FILL,
    ]
