import numpy as np
import pandas as pd

from alpha.factor.timeline import Timeline, build_timeline, compact_observed
from tools.data.types import DataFreq
from tools.factors.expr.timeline import build_panel_timeline


def test_public_timeline_unions_sparse_sources_without_confusing_nan_with_absence():
    index = pd.date_range("2026-01-05 09:01", periods=3, freq="min")
    left = pd.DataFrame({"CLOSE": [1, np.nan]}, index=index[[0, 2]])
    right = pd.DataFrame({"CLOSE": [2, 3]}, index=index[[1, 2]])
    public = build_timeline(("A", "B"), {"A": left, "B": right})
    adapted = build_panel_timeline(("A", "B"), DataFreq.MIN1, {("A", "MIN1"): left, ("B", "MIN1"): right})
    assert isinstance(adapted, Timeline)
    pd.testing.assert_index_equal(public.index, index)
    np.testing.assert_array_equal(public.observed, [[1, 0, 1], [0, 1, 1]])
    np.testing.assert_array_equal(public.observed, adapted.observed)
    np.testing.assert_array_equal(public.times_ns, adapted.times_ns)
    assert public.observed_mask is public.observed_mask
    from tools.factors.expr.timeline import compact_observed as adapted_compact
    assert adapted_compact is compact_observed


def test_timeline_alignment_preserves_authoritative_night_trading_day():
    day = pd.Timestamp("2026-01-06")
    times = pd.to_datetime(["2026-01-05 21:01", "2026-01-06 09:01"])
    index = pd.MultiIndex.from_arrays([[day, day], times], names=["trading_day", "trade_time"])
    frame = pd.DataFrame({"CLOSE": [1, 2]}, index=index)
    timeline = build_panel_timeline(("A",), DataFreq.MIN1, {("A", "MIN1"): frame})
    aligned = timeline.align(index[:1], ["A"])
    assert aligned.trading_days[0] == day
    assert aligned.times_ns[0] == times.as_unit("ns").asi8[0]
    assert aligned.dense_same_session


def test_timeline_filters_frozen_frequency_and_product_set():
    minute = pd.DataFrame({"CLOSE": [1]}, index=pd.to_datetime(["2026-01-06 09:01"]))
    extra = pd.DataFrame({"CLOSE": [2]}, index=pd.to_datetime(["2030-01-01"]))
    timeline = build_panel_timeline(("A",), DataFreq.MIN1,
        {("A", "MIN1"): minute, ("A", "DAY1"): extra, ("B", "MIN1"): extra})
    pd.testing.assert_index_equal(timeline.index, minute.index)


def test_different_frozen_session_calendars_do_not_share_one_scope_node():
    from alpha.factor import ColumnRef, EvalContext, TradingSession, scope_session
    from alpha.factor.plan import compile_plan
    index = pd.to_datetime([1, 2, 3, 4], unit="ns")
    frame = pd.DataFrame({"CLOSE": [1, 3, 9, 13]}, index=index)
    close = ColumnRef("CLOSE")
    first = close.groupby_scope(scope_session((TradingSession(0, 2), TradingSession(3, 5)))).mean()
    second = close.groupby_scope(scope_session((TradingSession(0, 5),))).mean()
    outputs = compile_plan([first, second], EvalContext(products=("A",), preloaded={"A": frame}))
    np.testing.assert_allclose(outputs[0]["A"], [1, 2, 9, 11])
    np.testing.assert_allclose(outputs[1]["A"], [1, 2, 13 / 3, 6.5])
