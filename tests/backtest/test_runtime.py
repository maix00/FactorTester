from __future__ import annotations

import pandas as pd
import pytest

from tools.backtest_engines.event_driven.runtime import (
    EventDraft,
    EventRuntime,
    EventTopic,
    MarketSlice,
    MarketSliceBarrier,
    ProductPrice,
    ReplayEventSource,
)


def test_replay_source_keeps_only_one_market_event_pending() -> None:
    timestamps = pd.date_range("2026-01-01", periods=3, freq="D")
    runtime = EventRuntime("run-1")
    source = ReplayEventSource(timestamps, range(3))
    pending_during_handler: list[int] = []

    def on_market(event, runtime):
        pending_during_handler.append(runtime.pending_count)

    runtime.add_source(source)
    runtime.subscribe(EventTopic.MARKET_DATA, on_market)
    runtime.run()

    assert pending_during_handler == [0, 0, 0]
    assert [item.event.payload for item in runtime.journal] == [0, 1, 2]


def test_signal_causes_order_then_fill_at_same_timestamp() -> None:
    timestamp = pd.Timestamp("2026-01-01 09:01")
    runtime = EventRuntime("run-2")
    runtime.add_source(ReplayEventSource([timestamp], [{"signal": 1.0}]))

    runtime.subscribe(
        EventTopic.MARKET_DATA,
        lambda event, _: EventDraft(
            EventTopic.FACTOR_SIGNAL, event.timestamp, event.payload["signal"]
        ),
    )
    runtime.subscribe(
        EventTopic.FACTOR_SIGNAL,
        lambda event, _: EventDraft(
            EventTopic.ORDER_SUBMITTED, event.timestamp, {"quantity": event.payload}
        ),
    )
    runtime.subscribe(
        EventTopic.ORDER_SUBMITTED,
        lambda event, _: EventDraft(EventTopic.FILL, event.timestamp, event.payload),
    )
    runtime.run()

    topics = [item.event.topic for item in runtime.journal]
    assert topics == [
        EventTopic.MARKET_DATA,
        EventTopic.FACTOR_SIGNAL,
        EventTopic.ORDER_SUBMITTED,
        EventTopic.FILL,
    ]
    events = [item.event for item in runtime.journal]
    assert events[1].causation_id == events[0].event_id
    assert events[2].causation_id == events[1].event_id
    assert events[3].causation_id == events[2].event_id


def test_delayed_fill_is_ordered_against_future_market_data() -> None:
    timestamps = pd.to_datetime(["2026-01-01 09:01", "2026-01-01 09:02"])
    runtime = EventRuntime("run-3")
    runtime.add_source(ReplayEventSource(timestamps, [1, 2]))

    def on_market(event, _):
        if event.payload == 1:
            return EventDraft(EventTopic.FILL, timestamps[1], "delayed")
        return None

    runtime.subscribe(EventTopic.MARKET_DATA, on_market)
    runtime.run()

    assert [(item.event.topic, item.event.payload) for item in runtime.journal] == [
        (EventTopic.MARKET_DATA, 1),
        (EventTopic.MARKET_DATA, 2),
        (EventTopic.FILL, "delayed"),
    ]


def test_events_cannot_be_published_into_the_past() -> None:
    timestamp = pd.Timestamp("2026-01-01 09:01")
    runtime = EventRuntime("run-4")
    runtime.add_source(ReplayEventSource([timestamp], [1]))

    def time_travel(event, _):
        return EventDraft(EventTopic.FILL, timestamp - pd.Timedelta(minutes=1))

    runtime.subscribe(EventTopic.MARKET_DATA, time_travel)
    with pytest.raises(ValueError, match="past"):
        runtime.run()


def test_market_slice_barrier_triggers_cross_sectional_event() -> None:
    timestamp = pd.Timestamp("2026-01-01 09:01")
    prices = [ProductPrice("A", 10.0), ProductPrice("B", 20.0)]
    runtime = EventRuntime("run-5")
    runtime.add_source(ReplayEventSource([timestamp, timestamp], prices))
    barrier = MarketSliceBarrier(["A", "B"])
    runtime.add_finalizer(barrier.finalize)
    closed: list[MarketSlice] = []
    runtime.subscribe(EventTopic.MARKET_DATA, barrier.on_price)
    runtime.subscribe(
        EventTopic.MARKET_SLICE_CLOSED,
        lambda event, _: closed.append(event.payload),
    )
    runtime.run()

    assert len(closed) == 1
    assert set(closed[0].prices) == {"A", "B"}


def test_incomplete_final_market_slice_fails() -> None:
    timestamp = pd.Timestamp("2026-01-01 09:01")
    runtime = EventRuntime("run-incomplete")
    runtime.add_source(ReplayEventSource([timestamp], [ProductPrice("A", 10.0)]))
    barrier = MarketSliceBarrier(["A", "B"])
    runtime.subscribe(EventTopic.MARKET_DATA, barrier.on_price)
    runtime.add_finalizer(barrier.finalize)

    with pytest.raises(ValueError, match=r"missing products: \['B'\]"):
        runtime.run()


def test_runtime_is_single_use_and_subscriptions_freeze() -> None:
    runtime = EventRuntime("run-6")
    runtime.run()
    with pytest.raises(RuntimeError, match="single-use"):
        runtime.run()
    with pytest.raises(RuntimeError, match="immutable"):
        runtime.subscribe(EventTopic.REPORT, lambda event, runtime: None)
