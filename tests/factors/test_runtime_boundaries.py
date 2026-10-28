"""Exercise event-line -> shared Rust DAG, with no Python state-machine fallback."""
import numpy as np
import pandas as pd
import pytest

from tools.data.types import DataColumn, DataFreq
from tools.factors.events import EventId
from tools.factors.expr.groupby_scope import GroupByScopeExpr
from tools.factors.expr.leaf import ColumnRef
from tools.factors.expr.lookback_scope import scope_trading_day, scope_session
from tools.factors.expr.streaming.incremental import compile_incremental_factors


class Events:
    def __init__(self):
        self.occurrences = {}

    def latest(self, event):
        return self.occurrences.get(event)


def test_event_line_compiles_shared_boundaries_and_resets_each_scope():
    events = Events()
    close = ColumnRef(DataColumn.CLOSE)
    day = GroupByScopeExpr(scope_trading_day(), close)
    session = GroupByScopeExpr(scope_session(), close)
    executor = compile_incremental_factors(
        {"day_mean": day.mean(), "day_sum": day.sum(), "session": session.mean()},
        ("A",), source_freq=DataFreq.MIN1, event_line=events, require_rust=True,
    )
    assert executor.uses_rust
    assert len(executor._boundaries) == 2
    outputs = []
    for ordinal, value in enumerate([10, 20, 100, 300], start=1):
        events.occurrences[EventId.TRADING_DAY_START] = 1 if ordinal < 3 else 3
        events.occurrences[EventId.TRADING_SESSION_START] = 1 if ordinal < 2 else 2
        stamp = pd.Timestamp(ordinal, unit="ns")
        executor.on_bar(stamp, {"A": {"CLOSE": value}})
        outputs.append(executor.on_signal(stamp))
    np.testing.assert_allclose([row["day_mean"]["A"] for row in outputs], [10, 15, 100, 200])
    np.testing.assert_allclose([row["day_sum"]["A"] for row in outputs], [10, 30, 100, 400])
    np.testing.assert_allclose([row["session"]["A"] for row in outputs], [10, 20, 60, 140])


def test_explicit_boundary_flags_can_differ_between_products():
    expression = GroupByScopeExpr(scope_trading_day(), ColumnRef(DataColumn.CLOSE)).mean()
    executor = compile_incremental_factors({"mean": expression}, ("A", "B"), source_freq=DataFreq.MIN1, require_rust=True)
    with pytest.raises(ValueError, match="authoritative boundary"):
        executor.on_bar(pd.Timestamp(0), {"A": {"CLOSE": 1}, "B": {"CLOSE": 10}})
    for ordinal, values, flags in [(0, (1, 10), (True, True)), (1, (3, 30), (False, True))]:
        executor.on_bar(pd.Timestamp(ordinal), {product: {"CLOSE": value} for product, value in zip(("A", "B"), values)},
                        boundary_flags={"trading_day_start": dict(zip(("A", "B"), flags))})
    assert executor.on_signal(pd.Timestamp(1))["mean"] == {"A": 2, "B": 30}
