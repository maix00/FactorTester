from __future__ import annotations

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.flow import Phase
from tools.testers.backtest.engines.native.scheduler import FlowContext, ResolvedFlow, SchedulerError
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.base import FieldRef

REF = FieldRef("x", owner="X")


class _FakeQueue:
    def __init__(self) -> None:
        self.pushed: list[EventDraft] = []

    def push_event(self, draft: EventDraft) -> None:
        self.pushed.append(draft)


class _BulkFakeQueue(_FakeQueue):
    def __init__(self) -> None:
        super().__init__()
        self.bulk_called = False

    def push_events(self, drafts: list[EventDraft]) -> None:
        self.bulk_called = True
        self.pushed.extend(drafts)


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


def test_set_pushes_list_of_event_drafts_in_bulk_when_available():
    queue = _BulkFakeQueue()
    ctx = FlowContext(timestamp=None, event_queue=queue)
    s = Strategy(alias="S")
    drafts = [
        EventDraft(EventKind.SIGNAL, pd.Timestamp("2024-01-01"), s),
        EventDraft(EventKind.SIGNAL, pd.Timestamp("2024-01-02"), s),
    ]
    ctx.set(REF, drafts)
    assert queue.bulk_called is True
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


def _resolved_flow(*, inputs=(), outputs=()) -> ResolvedFlow:
    return ResolvedFlow(
        name="flow",
        owner="TestModule",
        inputs=inputs,
        outputs=outputs,
        phase=Phase.PRE_REPLAY,
        event_kind=None,
        order=1,
        after=(),
        before=(),
        compute=lambda _account, _ctx: None,
        description="",
        strategy_scoped=False,
    )


def test_flow_context_tracks_declared_field_contract():
    ctx = FlowContext(timestamp=None, event_queue=_FakeQueue())
    ctx.enter_flow(_resolved_flow(inputs=(REF,), outputs=(REF,)))
    ctx.get(REF)
    ctx.set(REF, 1)
    ctx.exit_flow()
    assert ctx.contract_violations() == ()


def test_flow_context_records_undeclared_field_access():
    ctx = FlowContext(timestamp=None, event_queue=_FakeQueue(), audit_contract=True)
    ctx.enter_flow(_resolved_flow(outputs=()))
    ctx.set(REF, 1)
    ctx.exit_flow()

    assert ctx.contract_violations() == ({
        "flow": "TestModule.flow",
        "phase": "pre_replay",
        "event_kind": "",
        "access": "write",
        "field": "X.x",
    },)


def test_flow_context_strict_contract_raises():
    ctx = FlowContext(timestamp=None, event_queue=_FakeQueue(), enforce_contract=True)
    ctx.enter_flow(_resolved_flow(outputs=()))
    try:
        import pytest

        with pytest.raises(SchedulerError, match="undeclared write"):
            ctx.set(REF, 1)
    finally:
        ctx.exit_flow()


def test_flow_context_contract_audit_is_off_by_default():
    ctx = FlowContext(timestamp=None, event_queue=_FakeQueue())
    ctx.enter_flow(_resolved_flow(outputs=()))
    ctx.set(REF, 1)
    ctx.exit_flow()
    assert ctx.contract_violations() == ()
