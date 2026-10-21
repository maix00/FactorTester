"""Bounded OHLCV projection for browser chart ranges."""

from __future__ import annotations

import math
from bisect import bisect_left
from typing import Any, Mapping

import numpy as np
import pandas as pd

from tools.data.types import DataFreq, finest_index

from .errors import ProductMarketDataError


_CHART_INTERVALS = {
    "MIN5": "5min", "MIN15": "15min", "MIN30": "30min",
    "HOUR1": "1h", "DAY1": "1D", "WEEK1": "W-SUN",
}


def fixed_chart_frame(
    frame: pd.DataFrame, request: Mapping[str, Any],
    price_columns: tuple[str, str, str, str, str],
    source_frequency: DataFreq,
    oi_column: str | None = None,
    *, time_column: str | None = None,
    trading_day_column: str | None = None,
    source_delivery_mode: str = "historical_snapshot",
) -> tuple[pd.DataFrame, int]:
    """Aggregate to the explicitly selected calendar/trading interval only.

    A request over the row budget fails rather than silently changing the
    selected candle frequency or returning a misleading subset of candles.
    """
    interval = str(request.get("chart_interval") or "SOURCE").upper()
    if interval == "LIVE":
        if source_delivery_mode != "live_stream":
            raise ProductMarketDataError("所选数据源不提供实时 K 线")
        interval = "SOURCE"
    if interval != "SOURCE" and interval not in _CHART_INTERVALS:
        raise ProductMarketDataError("不支持的图表数据频率")
    interval_duration = (pd.Timedelta(days=7) if interval == "WEEK1"
                         else DataFreq(interval).value if interval != "SOURCE" else None)
    if interval_duration is not None and interval_duration < source_frequency.value:
        raise ProductMarketDataError("图表数据频率不能细于数据源频率")
    if interval == "SOURCE" or frame.empty:
        result = frame
    else:
        stamps = pd.DatetimeIndex(pd.to_datetime(
            frame[time_column] if time_column else finest_index(frame.index),
        ))
        if interval in ("DAY1", "WEEK1") and trading_day_column \
                and trading_day_column in frame:
            days = pd.DatetimeIndex(pd.to_datetime(frame[trading_day_column]))
        elif interval in ("DAY1", "WEEK1") and isinstance(frame.index, pd.MultiIndex):
            from tools.data.types.time_index import DataIndex
            days = DataIndex(frame.index).trading_day_index()
        else:
            days = stamps.normalize()
        if interval == "WEEK1":
            keys = days.tz_localize(None).to_period("W-SUN").end_time.normalize()
        elif interval == "DAY1":
            keys = days
        else:
            # Source minute bars are end-stamped: 09:01 covers (09:00, 09:01].
            # A 5-minute candle at 09:05 therefore contains 09:01..09:05.
            keys = stamps.ceil(_CHART_INTERVALS[interval])
        open_col, high_col, low_col, close_col, volume_col = price_columns
        aggregate: dict[str, tuple[str, str]] = {
            open_col: (open_col, "first"), high_col: (high_col, "max"),
            low_col: (low_col, "min"), close_col: (close_col, "last"),
            volume_col: (volume_col, "sum"),
        }
        if oi_column:
            aggregate[oi_column] = (oi_column, "last")
        if time_column:
            aggregate[time_column] = (time_column, "first")
        result = frame.groupby(keys, sort=True).agg(**aggregate)
        if time_column:
            result[time_column] = result.index
            result = result.reset_index(drop=True)
    count = len(result)
    limit = _maximum_points(request)
    if count > limit:
        raise ProductMarketDataError(
            f"当前选择包含 {count:,} 根 K 线，超过单次图表上限 {limit:,} 根；"
            "请选择更粗的频率或更短的范围后保存")
    return result, count


def _maximum_points(request: Mapping[str, Any]) -> int:
    try:
        return min(5000, max(100, int(request.get("max_points") or 1200)))
    except (TypeError, ValueError):
        return 1200


def bounded_ohlcv_frame(
    frame: pd.DataFrame,
    request: Mapping[str, Any],
    price_columns: tuple[str, str, str, str, str],
    oi_column: str | None = None,
    *,
    time_column: str | None = None,
) -> tuple[pd.DataFrame, int]:
    """Aggregate before Python row conversion; preserve the source bar count.

    The buckets use the same contiguous source-bar boundaries as
    ``bounded_ohlcv_rows``. Event anchors still use that row-level path so
    their exact candles and neighbours are never changed by this fast path.
    """
    total = len(frame)
    maximum = _maximum_points(request)
    if total <= maximum or request.get("anchor_timestamps"):
        return frame, total
    width = math.ceil(total / maximum)
    groups = np.arange(total, dtype=np.int64) // width
    first = np.arange(0, total, width)
    last = np.minimum(first + width - 1, total - 1)
    open_col, high_col, low_col, close_col, volume_col = price_columns
    result: dict[str, Any] = {
        open_col: frame[open_col].to_numpy()[first],
        high_col: frame[high_col].groupby(groups, sort=False).max().to_numpy(),
        low_col: frame[low_col].groupby(groups, sort=False).min().to_numpy(),
        close_col: frame[close_col].to_numpy()[last],
        volume_col: frame[volume_col].groupby(groups, sort=False).sum().to_numpy(),
    }
    if oi_column:
        result[oi_column] = frame[oi_column].to_numpy()[last]
    if time_column:
        result[time_column] = frame[time_column].to_numpy()[last]
    sampled = pd.DataFrame(result, index=frame.index.take(last))
    return sampled, total


def bounded_ohlcv_rows(
    rows: list[dict[str, Any]], request: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """Aggregate contiguous bars without corrupting OHLCV semantics."""
    total = len(rows)
    maximum = _maximum_points(request)
    if total <= maximum:
        return rows, total
    width = math.ceil(total / maximum)
    sampled: list[dict[str, Any]] = []
    timestamps = [int(row["timestamp"]) for row in rows]
    anchors = request.get("anchor_timestamps") or []
    if not isinstance(anchors, list) or len(anchors) > 3000:
        raise ValueError("anchor_timestamps must be a list of at most 3000 timestamps")
    try:
        tolerance = max(0, int(request.get("anchor_tolerance_ms") or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid anchor_tolerance_ms") from exc
    pinned: set[int] = set()
    for value in anchors:
        try:
            target = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid anchor timestamp") from exc
        position = bisect_left(timestamps, target)
        candidates = [index for index in (position - 1, position) if 0 <= index < total]
        if candidates:
            nearest = min(candidates, key=lambda index: abs(timestamps[index] - target))
            if abs(timestamps[nearest] - target) <= tolerance:
                pinned.add(nearest)

    def aggregate(bucket: list[dict[str, Any]]) -> dict[str, Any]:
        first, last = bucket[0], bucket[-1]
        entry = {
            **last,
            "timestamp": last.get("timestamp"),
            "time": last.get("time"),
            "open": first.get("open"),
            "high": max(float(item["high"]) for item in bucket),
            "low": min(float(item["low"]) for item in bucket),
            "close": last.get("close"),
            "volume": sum(float(item.get("volume") or 0) for item in bucket),
        }
        if any("open_interest" in item for item in bucket):
            entry["open_interest"] = last.get("open_interest")
        return entry

    for offset in range(0, total, width):
        end = min(total, offset + width)
        segment = offset
        for index in range(offset, end):
            if index not in pinned:
                continue
            if segment < index:
                sampled.append(aggregate(rows[segment:index]))
            sampled.append(rows[index])
            segment = index + 1
        if segment < end:
            sampled.append(aggregate(rows[segment:end]))
    return sampled, total
