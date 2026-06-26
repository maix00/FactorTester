from __future__ import annotations

import pandas as pd

from tools.backtest_engines.factors.events import FactorSignal, PrecomputedFactorPublisher
from tools.backtest_engines.event_driven.runtime import (
    EventRuntime,
    EventTopic,
    MarketSliceBarrier,
    ProductPrice,
    ReplayEventSource,
)


def test_product_prices_trigger_vectorized_factor_signal() -> None:
    timestamp = pd.Timestamp("2026-01-01 09:01")
    runtime = EventRuntime("factor-run")
    runtime.add_source(ReplayEventSource(
        [timestamp, timestamp],
        [ProductPrice("A", 10.0), ProductPrice("B", 20.0)],
    ))
    barrier = MarketSliceBarrier(["A", "B"])
    publisher = PrecomputedFactorPublisher(
        "momentum",
        pd.DataFrame([[0.2, -0.1]], index=[timestamp], columns=["A", "B"]),
    )
    signals: list[FactorSignal] = []
    runtime.subscribe(EventTopic.MARKET_DATA, barrier.on_price)
    runtime.subscribe(EventTopic.MARKET_SLICE_CLOSED, publisher.on_market_slice)
    runtime.subscribe(
        EventTopic.FACTOR_SIGNAL,
        lambda event, _: signals.append(event.payload),
    )

    runtime.run()

    assert signals == [FactorSignal("momentum", {"A": 0.2, "B": -0.1})]
    topics = [record.event.topic for record in runtime.journal]
    assert topics == [
        EventTopic.MARKET_DATA,
        EventTopic.MARKET_DATA,
        EventTopic.MARKET_SLICE_CLOSED,
        EventTopic.FACTOR_SIGNAL,
    ]
