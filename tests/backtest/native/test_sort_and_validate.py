from __future__ import annotations

import pytest

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.engines.native.scheduler import (
    FlowRegistry, SchedulerError, sort_and_validate,
)
from tools.testers.backtest.modules.base import FieldRef

A = FieldRef("a", owner="X")
B = FieldRef("b", owner="X")
C = FieldRef("c", owner="X")


def _resolve(*flows):
    registry = FlowRegistry()
    for f in flows:
        registry.register_flow(f)
    return registry.resolve()


def test_normal_ordering_respected():
    fa = Flow("fa", inputs=(), outputs=(A,), phase=Phase.PRE_REPLAY, order=1, compute=lambda a, c: None)
    fb = Flow("fb", inputs=(A,), outputs=(B,), phase=Phase.PRE_REPLAY, order=2, compute=lambda a, c: None)
    fc = Flow("fc", inputs=(B,), outputs=(C,), phase=Phase.PRE_REPLAY, order=3, compute=lambda a, c: None)
    groups = sort_and_validate(_resolve(fa, fb, fc))
    ordered = groups[(Phase.PRE_REPLAY, None)]
    assert [f.name for f in ordered] == ["fa", "fb", "fc"]


def test_order_reversed_raises():
    fa = Flow("fa", inputs=(), outputs=(A,), phase=Phase.PRE_REPLAY, order=2, compute=lambda a, c: None)
    fb = Flow("fb", inputs=(A,), outputs=(B,), phase=Phase.PRE_REPLAY, order=1, compute=lambda a, c: None)
    with pytest.raises(SchedulerError):
        sort_and_validate(_resolve(fa, fb))


def test_after_violation_raises():
    fa = Flow("fa", inputs=(), outputs=(), phase=Phase.PRE_REPLAY, order=2, compute=lambda a, c: None)
    fb = Flow("fb", inputs=(), outputs=(), phase=Phase.PRE_REPLAY, order=1, after=(fa,), compute=lambda a, c: None)
    with pytest.raises(SchedulerError):
        sort_and_validate(_resolve(fa, fb))


def test_cross_group_dependency_not_validated():
    # A is never produced within this group (simulating an account-level
    # field from outside) -- should NOT raise, since cross-group deps skip
    # position-checking by design.
    fb = Flow(
        "fb", inputs=(A,), outputs=(B,), phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL, order=1, compute=lambda a, c: None,
    )
    groups = sort_and_validate(_resolve(fb))
    assert len(groups[(Phase.PER_EVENT, EventKind.SIGNAL)]) == 1


def test_per_event_requires_event_kind():
    fb = Flow("fb", inputs=(), outputs=(), phase=Phase.PER_EVENT, compute=lambda a, c: None)
    with pytest.raises(SchedulerError):
        sort_and_validate(_resolve(fb))


def test_non_per_event_forbids_event_kind():
    fb = Flow(
        "fb", inputs=(), outputs=(), phase=Phase.PRE_REPLAY,
        event_kind=EventKind.SIGNAL, compute=lambda a, c: None,
    )
    with pytest.raises(SchedulerError):
        sort_and_validate(_resolve(fb))


def test_groups_are_isolated_order_only_compared_within_group():
    fa = Flow(
        "fa", inputs=(), outputs=(), phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL, order=999, compute=lambda a, c: None,
    )
    fb = Flow(
        "fb", inputs=(), outputs=(), phase=Phase.PER_EVENT,
        event_kind=EventKind.ORDER, order=1, compute=lambda a, c: None,
    )
    groups = sort_and_validate(_resolve(fa, fb))
    assert len(groups[(Phase.PER_EVENT, EventKind.SIGNAL)]) == 1
    assert len(groups[(Phase.PER_EVENT, EventKind.ORDER)]) == 1
