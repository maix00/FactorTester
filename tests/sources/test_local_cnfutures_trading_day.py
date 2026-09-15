"""The local CN futures source accepts the engine's own time value.

The backtest engine hands data sources a ``tools.data.types.DataTime`` bound
(``.ts`` plus a precision), and the source used to pass it straight into
``pd.Timestamp`` — which raised deep inside pandas and failed the whole run.
"""

from __future__ import annotations

import pandas as pd

from sources.LocalCNFutures.CNFutures import _trading_day
from tools.data.types.time import DataTime


def test_trading_day_accepts_the_engine_time_value():
    bound = DataTime(ts=pd.Timestamp("2022-01-04"), precision="trading_day")
    assert _trading_day(bound) == pd.Timestamp("2022-01-04")


def test_trading_day_accepts_plain_bounds():
    assert _trading_day("2022-01-04") == pd.Timestamp("2022-01-04")
    assert _trading_day(pd.Timestamp("2022-01-04 03:00:00")) == pd.Timestamp(
        "2022-01-04"
    )


def test_trading_day_is_naive():
    aware = pd.Timestamp("2022-01-04 02:00:00", tz="Asia/Shanghai")
    assert _trading_day(aware).tzinfo is None
