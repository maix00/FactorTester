from __future__ import annotations

import pandas as pd

from tools.data.DataFreq import DataFreq
from tools.factors.FactorExpr import FactorExpr, build_panel_timeline
from tools.products.TradingSchedule import TradingSchedule


class _ScheduledProduct:
    def __init__(self, name: str, *sessions: str):
        self.name = name
        self.schedule = TradingSchedule.from_strings(*sessions)

    def get_trading_schedule(self):
        return self.schedule

    def __repr__(self):
        return self.name


def _frame(times: list[str]) -> pd.DataFrame:
    index = pd.to_datetime(times)
    return pd.DataFrame({"CLOSE": range(len(index))}, index=index)


def test_panel_timeline_distinguishes_closed_slots_from_missing_scheduled_bars():
    daytime = _ScheduledProduct("daytime", "09:00-09:02")
    longer = _ScheduledProduct("longer", "09:00-09:03")
    preloaded = {
        (daytime, "MIN1"): _frame(["2026-05-25 09:00", "2026-05-25 09:02"]),
        (longer, "MIN1"): _frame(
            ["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02", "2026-05-25 09:03"]
        ),
    }

    timeline = build_panel_timeline([daytime, longer], DataFreq.MIN1, preloaded)

    missing_bar = pd.Timestamp("2026-05-25 09:01")
    fill_slot = pd.Timestamp("2026-05-25 09:03")
    assert timeline.scheduled_mask.loc[missing_bar, daytime]
    assert not timeline.observed_mask.loc[missing_bar, daytime]
    assert not timeline.scheduled_mask.loc[fill_slot, daytime]
    assert not timeline.observed_mask.loc[fill_slot, daytime]
    assert timeline.schedule_complete
    assert timeline.same_session is False


def test_panel_timeline_exposes_dense_same_session_fast_path():
    left = _ScheduledProduct("left", "09:00-09:01")
    right = _ScheduledProduct("right", "09:00-09:01")
    data = _frame(["2026-05-25 09:00", "2026-05-25 09:01"])

    timeline = build_panel_timeline(
        [left, right],
        DataFreq.MIN1,
        {(left, "MIN1"): data, (right, "MIN1"): data},
    )

    assert timeline.same_session is True
    assert timeline.dense_same_session


def test_panel_timeline_does_not_infer_missing_schedule_from_observed_data():
    product = object()
    data = _frame(["2026-05-25 09:00"])

    timeline = build_panel_timeline([product], DataFreq.MIN1, {(product, "MIN1"): data})

    assert not timeline.schedule_complete
    assert timeline.missing_schedule_products == (product,)
    assert not timeline.scheduled_mask.iloc[0, 0]


def test_daily_timeline_does_not_require_intraday_schedule():
    product = object()
    data = _frame(["2026-05-23", "2026-05-25"])

    timeline = build_panel_timeline([product], DataFreq.DAY1, {(product, "DAY1"): data})

    assert timeline.schedule_complete
    assert timeline.scheduled_mask.iloc[:, 0].all()


def test_expression_evaluation_receives_timeline_context():
    product = _ScheduledProduct("product", "21:00-01:00")
    data = _frame(["2026-05-25 21:00", "2026-05-26 00:01"])
    timeline = build_panel_timeline([product], DataFreq.MIN1, {(product, "MIN1"): data})

    class _CaptureTimeline(FactorExpr):
        def _evaluate(self, ctx):
            return ctx.panel_timeline.scheduled_mask

        def _structural_key(self):
            return ("CaptureTimeline",)

    received = _CaptureTimeline().evaluate([product], DataFreq.MIN1, panel_timeline=timeline)

    assert received.loc[pd.Timestamp("2026-05-25 21:00"), product]
    assert received.loc[pd.Timestamp("2026-05-26 00:01"), product]
