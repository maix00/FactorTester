"""Helper utilities for shared price data routes."""

from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd


def to_utc_epoch(ts: pd.Timestamp, timezone: str = 'Asia/Shanghai') -> int:
    """将 pd.Timestamp 转为 UTC epoch（毫秒）。
    
    - naive ts → tz_localize(timezone) → tz_convert('UTC') → timestamp()
    - aware ts  → tz_convert('UTC') → timestamp()
    
    前端 Highcharts (useUTC=true) 会根据浏览器本地时区自动渲染。
    """
    if ts.tz is None:
        ts = ts.tz_localize(timezone)
    ts = ts.tz_convert('UTC')
    return int(ts.timestamp() * 1000)


def row_value_as_float(row, col: str, default=None):
    v = row.get(col)
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return default
    return float(v)


def format_price_row(row, time_col: str, o_col: str, h_col: str, l_col: str, c_col: str, v_col: str,
                     oi_col: str | None, freq_is_daily: bool, timezone: str = 'Asia/Shanghai'):
    ts: pd.Timestamp = cast(pd.Timestamp, pd.Timestamp(row[time_col]))
    entry: dict = {
        'time': ts.tz_localize(timezone).tz_convert('UTC').isoformat() if ts.tz is None else ts.tz_convert('UTC').isoformat(),
        'timestamp': to_utc_epoch(ts, timezone),
        'open': row_value_as_float(row, o_col),
        'high': row_value_as_float(row, h_col),
        'low': row_value_as_float(row, l_col),
        'close': row_value_as_float(row, c_col),
        'volume': row_value_as_float(row, v_col, 0),
    }
    if oi_col:
        entry['open_interest'] = row_value_as_float(row, oi_col, 0)
    return entry

