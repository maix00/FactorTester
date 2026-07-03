from __future__ import annotations

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.strategy import Strategy


def test_event_kind_values_and_ordering():
    assert list(EventKind) == [
        EventKind.BAR,
        EventKind.SIGNAL,
        EventKind.ORDER_NOTICE,
        EventKind.ORDER,
        EventKind.LEDGER_NOTICE,
    ]
    assert EventKind.BAR == 0
    assert EventKind.SIGNAL == 10
    assert EventKind.ORDER_NOTICE == 15
    assert EventKind.ORDER == 20
    assert EventKind.BAR < EventKind.SIGNAL
    assert EventKind.SIGNAL < EventKind.ORDER_NOTICE
    assert EventKind.ORDER_NOTICE < EventKind.ORDER
    assert EventKind.SIGNAL < EventKind.ORDER


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
