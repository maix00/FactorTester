from __future__ import annotations

import numpy as np
import pandas as pd

from tools.data.types import DataFreq
from tools.factors.FactorExpr import ConstExpr, ShiftOp, build_panel_timeline


class _Product:
    def __init__(self, name: str, day_periods: int = 240):
        self.name = name
        self.MIN1 = type("_Meta", (), {"day_periods": day_periods})()

    def __repr__(self):
        return self.name


def _frame(times: list[str], values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"CLOSE": values}, index=pd.to_datetime(times))


def _evaluate(data, products, preloaded, periods):
    timeline = build_panel_timeline(products, DataFreq.MIN1, preloaded)
    return ShiftOp("shift", ConstExpr(periods), ConstExpr(data)).evaluate(
        products=products, freq=DataFreq.MIN1, panel_timeline=timeline,
    )


def test_same_observed_slots_shift_matches_master_path():
    left = _Product("left")
    right = _Product("right")
    index = pd.to_datetime(["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02"])
    data = pd.DataFrame({left: [1.0, 2.0, 3.0], right: [4.0, 5.0, 6.0]}, index=index)
    preloaded = {
        (left, "MIN1"): _frame(list(index.astype(str)), [1.0, 2.0, 3.0]),
        (right, "MIN1"): _frame(list(index.astype(str)), [4.0, 5.0, 6.0]),
    }

    result = _evaluate(data, [left, right], preloaded, 1)

    pd.testing.assert_frame_equal(result, data.shift(1))


def test_async_shift_skips_rows_absent_from_initial_observed_mask():
    short = _Product("short")
    long = _Product("long")
    index = pd.to_datetime(["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02"])
    data = pd.DataFrame({short: [100.0, np.nan, 102.0], long: [10.0, 11.0, 12.0]}, index=index)
    preloaded = {
        (short, "MIN1"): _frame(["2026-05-25 09:00", "2026-05-25 09:02"], [100.0, 102.0]),
        (long, "MIN1"): _frame(list(index.astype(str)), [10.0, 11.0, 12.0]),
    }

    result = _evaluate(data, [short, long], preloaded, 1)

    assert result.loc[index[2], short] == 100.0
    assert np.isnan(result.loc[index[1], short])
    assert result.loc[index[2], long] == 11.0


def test_async_day_window_uses_each_products_resolved_bar_count():
    short = _Product("short", day_periods=2)
    long = _Product("long", day_periods=3)
    index = pd.to_datetime(
        ["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02",
         "2026-05-26 09:00", "2026-05-26 09:01", "2026-05-26 09:02"]
    )
    data = pd.DataFrame({
        short: [1.0, 2.0, np.nan, 3.0, 4.0, np.nan],
        long: [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
    }, index=index)
    preloaded = {
        (short, "MIN1"): data.loc[data[short].notna(), [short]].rename(columns={short: "CLOSE"}),
        (long, "MIN1"): data[[long]].rename(columns={long: "CLOSE"}),
    }

    result = _evaluate(data, [short, long], preloaded, pd.Timedelta(days=1))

    assert result.loc[index[3], short] == 1.0
    assert result.loc[index[3], long] == 10.0
    assert np.isnan(result.loc[index[5], short])
