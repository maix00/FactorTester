from __future__ import annotations

import pandas as pd

from tools.data.DataIndex import DataIndex


def test_settlement_bar_mask_uses_last_trade_time_of_each_calendar_day():
    index = pd.DatetimeIndex([
        "2026-01-05 09:01:00",
        "2026-01-05 15:00:00",
        "2026-01-05 21:00:00",
        "2026-01-05 23:00:00",
        "2026-01-06 09:01:00",
    ])

    mask = DataIndex(index).settlement_bar_mask()

    assert mask.tolist() == [False, False, False, True, True]


def test_settlement_bar_mask_ignores_outer_trading_day_level():
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

    mask = DataIndex(index).settlement_bar_mask()

    assert mask.tolist() == [False, True, False, True]
