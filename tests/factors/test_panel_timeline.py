from __future__ import annotations

import pandas as pd

from tools.data.types import DataFreq, DataTime
from tools.factors.FactorExpr import FactorExpr, build_panel_timeline


class _Product:
    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return self.name


def _frame(times: list[str]) -> pd.DataFrame:
    index = pd.to_datetime(times)
    return pd.DataFrame({"CLOSE": range(len(index))}, index=index)


def test_panel_timeline_uses_observed_slots_as_default_trading_slots():
    short = _Product("short")
    long = _Product("long")
    preloaded = {
        (short, "MIN1"): _frame(["2026-05-25 09:00", "2026-05-25 09:02"]),
        (long, "MIN1"): _frame(
            ["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02"]
        ),
    }

    timeline = build_panel_timeline([short, long], DataFreq.MIN1, preloaded)

    missing = pd.Timestamp("2026-05-25 09:01")
    assert not timeline.observed_mask.loc[missing, short]
    assert timeline.observed_mask.loc[missing, long]
    assert timeline.same_session is False


def test_panel_timeline_exposes_same_observed_slot_fast_path():
    left = _Product("left")
    right = _Product("right")
    data = _frame(["2026-05-25 09:00", "2026-05-25 09:01"])

    timeline = build_panel_timeline(
        [left, right], DataFreq.MIN1, {(left, "MIN1"): data, (right, "MIN1"): data},
    )

    assert timeline.same_session is True
    assert timeline.dense_same_session


def test_expression_evaluation_receives_observed_timeline_context():
    product = _Product("product")
    data = _frame(["2026-05-25 21:00", "2026-05-26 00:01"])
    timeline = build_panel_timeline([product], DataFreq.MIN1, {(product, "MIN1"): data})

    class _CaptureTimeline(FactorExpr):
        def _evaluate(self, ctx):
            return ctx.panel_timeline.observed_mask

        def _structural_key(self):
            return ("CaptureTimeline",)

    received = _CaptureTimeline().evaluate(
        [product],
        DataFreq.MIN1,
        start_dt=DataTime.from_dict({"date": "2026-05-25", "time": "21:00", "tz": "Asia/Shanghai"}, precision="exact"),
        end_dt=DataTime.from_dict({"date": "2026-05-26", "time": "00:01", "tz": "Asia/Shanghai"}, precision="exact"),
        panel_timeline=timeline,
    )

    pd.testing.assert_frame_equal(received, timeline.observed_mask)
