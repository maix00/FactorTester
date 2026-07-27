from __future__ import annotations

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.strategy import Strategy


def test_event_kind_values_and_ordering():
    assert list(EventKind) == [
        EventKind.FIELD_CHANGE,
        EventKind.MARKET_FEED,
        EventKind.BAR,
        EventKind.ORDER_STATUS,
        EventKind.ORDER,
        EventKind.SIGNAL,
        EventKind.LIFECYCLE_NOTICE,
        EventKind.TRADE_INTENT,
        EventKind.LEDGER,
    ]
    assert EventKind.BAR == 0
    assert EventKind.MARKET_FEED == -1
    assert EventKind.SIGNAL == 10
    assert EventKind.LIFECYCLE_NOTICE == 14
    assert EventKind.TRADE_INTENT == 15
    assert EventKind.ORDER == 5
    assert EventKind.ORDER_STATUS == 4
    assert EventKind.MARKET_FEED < EventKind.BAR < EventKind.ORDER
    assert EventKind.ORDER < EventKind.SIGNAL
    assert EventKind.SIGNAL < EventKind.LIFECYCLE_NOTICE
    assert EventKind.LIFECYCLE_NOTICE < EventKind.TRADE_INTENT
    assert EventKind.SIGNAL < EventKind.TRADE_INTENT


def test_event_draft_is_frozen_and_comparable():
    strategy = Strategy(alias="S1")
    ts = pd.Timestamp("2024-01-01")
    d1 = EventDraft(EventKind.SIGNAL, ts, strategy)
    d2 = EventDraft(EventKind.SIGNAL, ts, strategy)
    assert d1 == d2
    import dataclasses
    assert dataclasses.is_dataclass(EventDraft)
    try:
        d1.timestamp = pd.Timestamp("2024-01-02")  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("EventDraft should be frozen")
