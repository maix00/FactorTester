from types import SimpleNamespace

import numpy as np
import pandas as pd

from tools.factors.expr.streaming.calendar_window import (
    TradingCalendarWindow,
    TradingSession,
)
from tools.factors.expr.streaming.incremental import (
    RustIntervalNode,
    _SessionWindowResolver,
)


class _SequenceNode:
    def __init__(self):
        self.value = 0

    def update(self, market, cache):
        self.value += 1
        return np.array([float(self.value)])


def _calendar():
    return TradingCalendarWindow((
        TradingSession("2025-02-03", 0, 100, 2),
        TradingSession("2025-02-04", 1_000, 1_100, 3),
    ))


def _market(ns):
    return SimpleNamespace(timestamp=pd.Timestamp(ns, unit="ns"))


def test_session_sum_expands_and_evicts_in_o1_state():
    node = RustIntervalNode(
        "rolling_sum", _SequenceNode(), 1,
        _SessionWindowResolver(_calendar(), 2),
    )
    # day 1: only one session exists, window = 2 bars
    assert node.update(_market(10), {})[0] == 1
    assert node.update(_market(20), {})[0] == 3
    # day 2: window becomes 5 bars; values 3,4,5 are added
    assert node.update(_market(1_010), {})[0] == 6
    assert node.update(_market(1_020), {})[0] == 10
    assert node.update(_market(1_030), {})[0] == 15
