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
                     oi_col: str | None, freq_is_daily: bool):
    ts = pd.Timestamp(row[time_col])
    entry = {
        'time': ts.strftime('%Y-%m-%d' if freq_is_daily else '%Y-%m-%d %H:%M:%S'),
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

