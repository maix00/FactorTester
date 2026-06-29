from __future__ import annotations

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.scheduler import EventQueue
from tools.testers.backtest.engines.native.strategy import Strategy


def test_pop_order_by_timestamp_then_kind():
    queue = EventQueue()
    s = Strategy(alias="S")
    seen: list[tuple[pd.Timestamp, EventKind]] = []

    queue.set_dispatcher(EventKind.SIGNAL, lambda batch: seen.append((batch[0].timestamp, EventKind.SIGNAL)))
    queue.set_dispatcher(EventKind.ORDER, lambda batch: seen.append((batch[0].timestamp, EventKind.ORDER)))

    t1, t2 = pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")
    queue.push_event(EventDraft(EventKind.ORDER, t1, s))  # pushed first but ORDER value > SIGNAL
    queue.push_event(EventDraft(EventKind.SIGNAL, t1, s))
    queue.push_event(EventDraft(EventKind.SIGNAL, t2, s))
    queue.run_until_drained()

    assert seen == [(t1, EventKind.SIGNAL), (t1, EventKind.ORDER), (t2, EventKind.SIGNAL)]


def test_dynamic_push_during_handling_is_processed_in_order():
    queue = EventQueue()
    s = Strategy(alias="S")
    seen: list[pd.Timestamp] = []
    early = pd.Timestamp("2024-01-01")
    late = pd.Timestamp("2024-01-05")

    def on_order(batch: list[EventDraft]) -> None:
        seen.append(batch[0].timestamp)
        if batch[0].timestamp == late:
            queue.push_event(EventDraft(EventKind.ORDER, early, s))

    queue.set_dispatcher(EventKind.ORDER, on_order)
    queue.push_event(EventDraft(EventKind.ORDER, late, s))
    queue.run_until_drained()

    assert seen == [late, early]


def test_batches_same_timestamp_and_kind_across_strategies():
    queue = EventQueue()
    s1, s2, s3 = Strategy(alias="S1"), Strategy(alias="S2"), Strategy(alias="S3")
    batches: list[list[EventDraft]] = []
    queue.set_dispatcher(EventKind.SIGNAL, lambda batch: batches.append(batch))
    queue.set_dispatcher(EventKind.ORDER, lambda batch: batches.append(batch))

    t = pd.Timestamp("2024-01-01")
    queue.push_event(EventDraft(EventKind.SIGNAL, t, s1))
    queue.push_event(EventDraft(EventKind.SIGNAL, t, s2))
    queue.push_event(EventDraft(EventKind.ORDER, t, s3))  # different kind, not in same batch
    queue.run_until_drained()

    assert len(batches) == 2
    signal_batch = next(b for b in batches if b[0].kind == EventKind.SIGNAL)
    order_batch = next(b for b in batches if b[0].kind == EventKind.ORDER)
    assert {d.strategy for d in signal_batch} == {s1, s2}
    assert {d.strategy for d in order_batch} == {s3}
