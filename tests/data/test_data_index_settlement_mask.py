from __future__ import annotations

import pandas as pd

from tools.data.DataIndex import DataIndex


def test_end_of_trading_day_uses_last_bar_of_each_trading_day():
    index = pd.MultiIndex.from_arrays(
        [
            pd.DatetimeIndex([
                "2026-01-06",
                "2026-01-06",
                "2026-01-06",
                "2026-01-06",
                "2026-01-07",
            ]),
            pd.DatetimeIndex([
                "2026-01-05 21:00:00",
                "2026-01-05 23:00:00",
                "2026-01-06 09:01:00",
                "2026-01-06 15:00:00",
                "2026-01-06 21:00:00",
            ]),
        ],
        names=["DAY1", "MIN1"],
    )

    mask = DataIndex(index).end_of_trading_day()

    assert mask.tolist() == [False, False, False, True, True]


def test_end_of_trading_day_ignores_outer_trading_day_level():
    index = pd.MultiIndex.from_arrays(
        [
            pd.DatetimeIndex([
                "2026-01-05",
                "2026-01-05",
                "2026-01-06",
                "2026-01-06",
            ]),
            pd.DatetimeIndex([
                "2026-01-05 21:00:00",
                "2026-01-05 23:00:00",
                "2026-01-06 09:01:00",
                "2026-01-06 15:00:00",
            ]),
        ],
        names=["DAY1", "MIN1"],
    )

    mask = DataIndex(index).end_of_trading_day()

    assert mask.tolist() == [False, True, False, True]


def test_end_of_trading_day_recognizes_trading_day_level_name():
    index = pd.MultiIndex.from_arrays(
        [
            pd.DatetimeIndex([
                "2026-01-05",
                "2026-01-05",
                "2026-01-06",
                "2026-01-06",
            ]),
            pd.DatetimeIndex([
                "2026-01-05 21:00:00",
                "2026-01-05 23:00:00",
                "2026-01-06 09:01:00",
                "2026-01-06 15:00:00",
            ]),
        ],
        names=["trading_day", "MIN1"],
    )

    mask = DataIndex(index).end_of_trading_day()

    assert mask.tolist() == [False, True, False, True]
