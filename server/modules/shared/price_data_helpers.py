"""Helper utilities for shared price data routes."""

from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd


_OPEN_INTEREST_ALIASES = frozenset({
    "openinterest",
    "oi",
    "position",
    "positioninterest",
    "hold",
    "持仓量",
})


def _normalized_column_name(value: object) -> str:
    """Normalize provider column spellings without changing the source frame."""
    return "".join(
        character for character in str(value or "").strip().lower()
        if character.isalnum()
    )


def open_interest_column(columns) -> str | None:
    """Return the actual open-interest column exposed by a provider.

    Product views normally expose ``OPEN_INTEREST`` after applying their
    ``DataColumn`` mapping, while contract files and third-party providers may
    keep ``open_interest``, ``OI``, ``hold`` or a localized spelling.  The
    projection must preserve the provider's actual column name so callers can
    read it without mutating the input frame.
    """
    values = [str(getattr(column, "name", column)) for column in columns]
    for value in values:
        if value == "OPEN_INTEREST":
            return value
    for value in values:
        if _normalized_column_name(value) in _OPEN_INTEREST_ALIASES:
            return value
    return None


def to_epoch_ms(
    ts: pd.Timestamp,
    timezone: str = 'Asia/Shanghai',
    *,
    use_utc: bool = False,
) -> int:
    """将 pd.Timestamp 转为 epoch 毫秒，统一入口。

    - use_utc=True  → tz_localize(timezone) → tz_convert('UTC') → timestamp()
                      （Highcharts useUTC=true）
    - use_utc=False → tz_localize(timezone) → .timestamp()，不走 UTC 转换
                      （Highcharts useUTC=false）
    - aware ts → 不重复 localize，仅按 use_utc 决定是否转 UTC。
    """
    if ts.tz is None:
        ts = ts.tz_localize(timezone)
    if use_utc:
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
        'timestamp': to_epoch_ms(ts, timezone, use_utc=True),
        'open': row_value_as_float(row, o_col),
        'high': row_value_as_float(row, h_col),
        'low': row_value_as_float(row, l_col),
        'close': row_value_as_float(row, c_col),
        'volume': row_value_as_float(row, v_col, 0),
    }
    if oi_col:
        entry['open_interest'] = row_value_as_float(row, oi_col, 0)
    return entry
