from __future__ import annotations

import pandas as pd

from tools.backtest_engines.event_driven.contracts import Order, OrderSide
from tools.backtest_engines.event_driven.runtime import (
    EventDraft,
    EventRuntime,
    EventTopic,
    ProductPrice,
    ReplayEventSource,
)
from tools.backtest_engines.execution.trading import VolumeParticipationBroker
from tools.backtest_engines.market_rules import (
    RuleFallbackPolicy,
    RuleUsageJournal,
    TemporalRuleProvider,
)


def order(order_id: str, portfolio_id: str, quantity: float, timestamp) -> Order:
    return Order(
        order_id=order_id,
        strategy_id=f"strategy-{portfolio_id}",
        portfolio_id=portfolio_id,
        timestamp=timestamp,
        instrument="A",
        side=OrderSide.BUY,
        quantity=quantity,
    )


def test_volume_capacity_creates_partial_fills_and_keeps_order_open() -> None:
    timestamps = pd.date_range("2026-01-01 09:01", periods=3, freq="min")
    runtime = EventRuntime("partial-fill")
    runtime.add_source(ReplayEventSource(
        timestamps,
        [
            ProductPrice("A", 100.0, {"VOLUME": 4.0}),
            ProductPrice("A", 101.0, {"VOLUME": 10.0}),
            ProductPrice("A", 102.0, {"VOLUME": 10.0}),
        ],
    ))
    broker = VolumeParticipationBroker({"portfolio"}, participation_rate=0.5)
    runtime.subscribe(EventTopic.MARKET_DATA, broker.on_market_data)
    runtime.subscribe(EventTopic.ORDER_SUBMITTED, broker.on_order_submitted)
    runtime.publish(EventDraft(
        EventTopic.ORDER_SUBMITTED,
        timestamps[0],
        order("order-1", "portfolio", 10.0, timestamps[0]),
    ))
    runtime.run()

    fills = [
        record.event.payload
        for record in runtime.journal
        if record.event.topic == EventTopic.FILL
    ]
    assert [fill.quantity for fill in fills] == [2.0, 5.0, 3.0]
    assert [fill.price for fill in fills] == [100.0, 101.0, 102.0]
    assert broker.open_order_count == 0


def test_shared_broker_capacity_is_consumed_across_strategies() -> None:
    timestamp = pd.Timestamp("2026-01-01 09:01")
    runtime = EventRuntime("shared-capacity")
    runtime.add_source(ReplayEventSource(
        [timestamp], [ProductPrice("A", 100.0, {"VOLUME": 10.0})]
    ))
    broker = VolumeParticipationBroker({"p1", "p2"}, participation_rate=0.5)
    runtime.subscribe(EventTopic.MARKET_DATA, broker.on_market_data)
    runtime.subscribe(EventTopic.ORDER_SUBMITTED, broker.on_order_submitted)
    runtime.publish(EventDraft(
        EventTopic.ORDER_SUBMITTED, timestamp, order("o1", "p1", 4.0, timestamp)
    ))
    runtime.publish(EventDraft(
        EventTopic.ORDER_SUBMITTED, timestamp, order("o2", "p2", 4.0, timestamp)
    ))
    runtime.run()

    fills = [
        record.event.payload
        for record in runtime.journal
        if record.event.topic == EventTopic.FILL
    ]
    assert [(fill.portfolio_id, fill.quantity) for fill in fills] == [
        ("p1", 4.0),
        ("p2", 1.0),
    ]
    assert broker.open_order_count == 1


def test_isolated_brokers_do_not_make_candidate_groups_compete() -> None:
    timestamp = pd.Timestamp("2026-01-01 09:01")
    runtime = EventRuntime("isolated-capacity")
    runtime.add_source(ReplayEventSource(
        [timestamp], [ProductPrice("A", 100.0, {"VOLUME": 10.0})]
    ))
    brokers = [
        VolumeParticipationBroker({"p1"}, participation_rate=0.5),
        VolumeParticipationBroker({"p2"}, participation_rate=0.5),
    ]
    for broker in brokers:
        runtime.subscribe(EventTopic.MARKET_DATA, broker.on_market_data)
        runtime.subscribe(EventTopic.ORDER_SUBMITTED, broker.on_order_submitted)
    runtime.publish(EventDraft(
        EventTopic.ORDER_SUBMITTED, timestamp, order("o1", "p1", 4.0, timestamp)
    ))
    runtime.publish(EventDraft(
        EventTopic.ORDER_SUBMITTED, timestamp, order("o2", "p2", 4.0, timestamp)
    ))
    runtime.run()

    fills = [
        record.event.payload
        for record in runtime.journal
        if record.event.topic == EventTopic.FILL
    ]
    assert [(fill.portfolio_id, fill.quantity) for fill in fills] == [
        ("p1", 4.0),
        ("p2", 4.0),
    ]


def test_liquidity_participation_is_resolved_from_replaceable_provider() -> None:
    timestamp = pd.Timestamp("2026-01-01 09:01")
    usage = RuleUsageJournal()
    broker = VolumeParticipationBroker(
        {"portfolio"},
        participation_rate=1.0,
        participation_provider=TemporalRuleProvider({}, latest={"A": 0.25}),
        fallback=RuleFallbackPolicy.LATEST_AVAILABLE,
        rule_usage=usage,
    )
    runtime = EventRuntime("provider-capacity")
    runtime.add_source(ReplayEventSource(
        [timestamp], [ProductPrice("A", 100.0, {"VOLUME": 8.0})]
    ))
    runtime.subscribe(EventTopic.MARKET_DATA, broker.on_market_data)
    runtime.subscribe(EventTopic.ORDER_SUBMITTED, broker.on_order_submitted)
    runtime.publish(EventDraft(
        EventTopic.ORDER_SUBMITTED,
        timestamp,
        order("o", "portfolio", 5.0, timestamp),
    ))
    runtime.run()

    fills = [
        record.event.payload for record in runtime.journal
        if record.event.topic == EventTopic.FILL
    ]
    assert [fill.quantity for fill in fills] == [2.0]
    assert usage.approximation_count == 1
