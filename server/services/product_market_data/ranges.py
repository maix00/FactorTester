"""Time-range helpers for product market-data projections."""

from __future__ import annotations

import pandas as pd


def range_bound(
    date_value: str | None,
    time_value: str | None,
    *,
    is_end: bool,
    precision: str | None = None,
) -> pd.Timestamp | None:
    if not date_value:
        return None
    text = str(date_value).strip()
    if not text:
        return None
    if precision == "trading_day":
        time_part = "23:59:59.999" if is_end else "00:00:00"
        return pd.Timestamp(f"{text} {time_part}")
    if time_value:
        return pd.Timestamp(f"{text} {time_value}")
    timestamp = pd.Timestamp(text)
    if is_end and len(text) <= 10:
        return timestamp + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
    return timestamp


def latest_relative_start(index: pd.DatetimeIndex, chart_range: str | None) -> pd.Timestamp | None:
    """Resolve a chart preset against the selected source's last available bar."""
    if not chart_range:
        return None
    if chart_range not in {"day", "month", "year", "ytd"}:
        raise ValueError(f"Unsupported chart range: {chart_range}")
    if index.empty:
        return None
    latest = pd.Timestamp(index.max())
    if chart_range == "day":
        return latest - pd.DateOffset(days=1)
    if chart_range == "month":
        return latest - pd.DateOffset(months=1)
    if chart_range == "year":
        return latest - pd.DateOffset(years=1)
    return latest.normalize().replace(month=1, day=1)
