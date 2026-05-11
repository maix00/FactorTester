"""Helper utilities for shared price data routes."""

from __future__ import annotations

import numpy as np
import pandas as pd


def row_value_as_float(row, col: str, default=None):
    v = row.get(col)
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return default
    return float(v)


def format_price_row(row, time_col: str, o_col: str, h_col: str, l_col: str, c_col: str, v_col: str,
                     oi_col: str | None, freq_is_daily: bool, timezone: str = 'Asia/Shanghai'):
    ts = pd.Timestamp(row[time_col])
    # 统一转为 UTC epoch，确保前端按浏览器本地时区正确渲染：
    # - 日内数据（有时区）：tz_convert('UTC') 后 timestamp()
    # - 日频数据（无时区）：先 tz_localize(product时区) 再 tz_convert('UTC') 后 timestamp()
    if ts.tz is None:
        ts = ts.tz_localize(timezone)
    ts = ts.tz_convert('UTC')
    entry = {
        'time': ts.isoformat(),
        'timestamp': int(ts.timestamp() * 1000),
        'open': row_value_as_float(row, o_col),
        'high': row_value_as_float(row, h_col),
        'low': row_value_as_float(row, l_col),
        'close': row_value_as_float(row, c_col),
        'volume': row_value_as_float(row, v_col, 0),
    }
    if oi_col:
        entry['open_interest'] = row_value_as_float(row, oi_col, 0)
    return entry

