from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.data.types import DataFreq
from tools.factors.FactorExpr import ConstExpr, build_panel_timeline
from tools.factors.expr.rolling import RollingExpr


class _Product:
    def __init__(self, name: str, day_periods: int = 240):
        self.name = name
        self.MIN1 = type("_Meta", (), {"day_periods": day_periods})()

    def __repr__(self):
        return self.name


def _timeline(data, products):
    preloaded = {
        (product, "MIN1"): data.loc[data[product].notna(), [product]].rename(columns={product: "CLOSE"})
        for product in products
    }
    return build_panel_timeline(products, DataFreq.MIN1, preloaded)


def _mean(data, products, window):
    return RollingExpr(ConstExpr(data), ConstExpr(window)).mean().evaluate(
        products=products, freq=DataFreq.MIN1, panel_timeline=_timeline(data, products),
    )


def test_same_observed_slots_rolling_matches_master_path():
    left = _Product("left")
    right = _Product("right")
    index = pd.to_datetime(["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02"])
    data = pd.DataFrame({left: [1.0, 2.0, 3.0], right: [10.0, 20.0, 30.0]}, index=index)

    result = _mean(data, [left, right], 2)

    pd.testing.assert_frame_equal(result, data.rolling(2, min_periods=1).mean())


def test_async_rolling_skips_rows_absent_from_initial_observed_mask():
    short = _Product("short")
    long = _Product("long")
    index = pd.to_datetime(["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02"])
    data = pd.DataFrame({short: [1.0, np.nan, 9.0], long: [10.0, 11.0, 12.0]}, index=index)

    result = _mean(data, [short, long], 2)

    assert result.loc[index[2], short] == 5.0
    assert np.isnan(result.loc[index[1], short])
    assert result.loc[index[2], long] == 11.5


def test_async_mixed_window_groups_each_products_resolved_periods():
    short = _Product("short", day_periods=2)
    long = _Product("long", day_periods=3)
    index = pd.to_datetime(
        ["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02",
         "2026-05-26 09:00", "2026-05-26 09:01", "2026-05-26 09:02"]
    )
    data = pd.DataFrame({
        short: [1.0, 3.0, np.nan, 5.0, 7.0, np.nan],
        long: [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
    }, index=index)

    result = _mean(data, [short, long], pd.Timedelta(days=1, minutes=1))

    assert result.loc[index[4], short] == 5.0
    assert result.loc[index[5], long] == 45.0
    assert np.isnan(result.loc[index[5], short])


def test_async_rolling_argmin_uses_compacted_matrix():
    short = _Product("short")
    long = _Product("long")
    index = pd.to_datetime(["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02"])
    data = pd.DataFrame({short: [5.0, np.nan, 1.0], long: [8.0, 4.0, 3.0]}, index=index)

    result = RollingExpr(ConstExpr(data), ConstExpr(2)).argmin_raw().evaluate(
        products=[short, long], freq=DataFreq.MIN1,
        panel_timeline=_timeline(data, [short, long]),
    )

    assert result.loc[index[2], short] == 1.0


def test_bars_rejects_async_day_window():
    short = _Product("short", day_periods=2)
    long = _Product("long", day_periods=3)
    operand = ConstExpr(pd.DataFrame({"dummy": [1.0]}))

    with pytest.raises(ValueError, match="scalar bar count"):
        RollingExpr(operand, ConstExpr(pd.Timedelta(days=1))).bars.evaluate(
            products=[short, long], freq=DataFreq.MIN1,
        )
