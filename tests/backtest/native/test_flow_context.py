from __future__ import annotations

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.scheduler import FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.base import FieldRef

REF = FieldRef("x", owner="X")


class _FakeQueue:
    def __init__(self) -> None:
        self.pushed: list[EventDraft] = []

    def push_event(self, draft: EventDraft) -> None:
        self.pushed.append(draft)


def test_set_get_roundtrip():
    ctx = FlowContext(timestamp=None, event_queue=_FakeQueue())
    assert ctx.get(REF, "default") == "default"
    ctx.set(REF, 42)
    assert ctx.get(REF) == 42


def test_set_pushes_single_event_draft():
    queue = _FakeQueue()
    ctx = FlowContext(timestamp=None, event_queue=queue)
    draft = EventDraft(EventKind.SIGNAL, pd.Timestamp("2024-01-01"), Strategy(alias="S"))
    ctx.set(REF, draft)
    assert queue.pushed == [draft]


def test_set_pushes_list_of_event_drafts():
    queue = _FakeQueue()
    ctx = FlowContext(timestamp=None, event_queue=queue)
    s = Strategy(alias="S")
    drafts = [
        EventDraft(EventKind.SIGNAL, pd.Timestamp("2024-01-01"), s),
        EventDraft(EventKind.SIGNAL, pd.Timestamp("2024-01-02"), s),
    ]
    ctx.set(REF, drafts)
    assert queue.pushed == drafts


def test_set_plain_value_does_not_push():
    queue = _FakeQueue()
    ctx = FlowContext(timestamp=None, event_queue=queue)
    ctx.set(REF, 3.14)
    assert queue.pushed == []


def test_set_for_keyed_by_field_and_strategy():
    queue = _FakeQueue()
    s1, s2 = Strategy(alias="S1"), Strategy(alias="S2")
    ctx = FlowContext(timestamp=None, event_queue=queue)
    ctx.set_for(REF, s1, 1.0)
    ctx.set_for(REF, s2, 2.0)
    assert ctx.get_for(REF, s1) == 1.0
    assert ctx.get_for(REF, s2) == 2.0
