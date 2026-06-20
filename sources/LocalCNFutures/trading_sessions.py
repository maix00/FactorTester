"""Infer scheduled futures sessions from observed minute-bar endpoints."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class ObservedTradingSessions:
    product_name: str
    observed_day_sessions: str
    observed_night_session: str | None
    observed_days: int
    source_mtime_ns: int
    inferred_at: str


def _minute_label(value: int) -> str:
    value %= 24 * 60
    return f"{value // 60:02d}:{value % 60:02d}"


def _contiguous_runs(minutes: list[int]) -> list[tuple[int, int]]:
    if not minutes:
        return []
    runs = []
    start = previous = minutes[0]
    for minute in minutes[1:]:
        if minute != previous + 1:
            runs.append((start, previous))
            start = minute
        previous = minute
    runs.append((start, previous))
    return runs


def infer_trading_sessions(
    frame: pd.DataFrame,
    *,
    product_name: str = "",
    min_day_ratio: float = 0.5,
    source_mtime_ns: int = 0,
) -> ObservedTradingSessions:
    """Infer day and night intervals from repeated MIN1 bar-end timestamps."""
    if "trade_time" not in frame or "trading_day" not in frame:
        raise ValueError("分钟数据必须包含 trade_time 和 trading_day")
    if frame.empty:
        raise ValueError(f"{product_name or '品种'}没有分钟数据")

    timestamps = pd.to_datetime(frame["trade_time"], errors="coerce")
    trading_days = pd.to_datetime(frame["trading_day"], errors="coerce").dt.normalize()
    valid = timestamps.notna() & trading_days.notna()
    if not valid.any():
        raise ValueError(f"{product_name or '品种'}没有有效分钟时间")

    minute_of_day = timestamps[valid].dt.hour * 60 + timestamps[valid].dt.minute
    observations = pd.DataFrame({"day": trading_days[valid], "minute": minute_of_day})
    observed_days = int(observations["day"].nunique())
    minimum_days = max(1, int(observed_days * float(min_day_ratio)))
    counts = observations.drop_duplicates().groupby("minute")["day"].nunique()
    minutes = sorted(int(value) for value in counts[counts >= minimum_days].index)
    runs = _contiguous_runs(minutes)

    day_runs = [(start, end) for start, end in runs if start >= 4 * 60 and end < 20 * 60]
    late_night = next(((start, end) for start, end in runs if start >= 20 * 60), None)
    early_night = next(((start, end) for start, end in runs if end < 4 * 60), None)

    day_sessions = ", ".join(
        f"{_minute_label(start - 1)}-{_minute_label(end)}"
        for start, end in day_runs
    )
    night_session = None
    if late_night is not None:
        night_start = late_night[0] - 1
        night_end = early_night[1] if early_night is not None else late_night[1]
        night_session = f"{_minute_label(night_start)}-{_minute_label(night_end)}"

    return ObservedTradingSessions(
        product_name=product_name,
        observed_day_sessions=day_sessions,
        observed_night_session=night_session,
        observed_days=observed_days,
        source_mtime_ns=int(source_mtime_ns),
        inferred_at=datetime.now(timezone.utc).isoformat(),
    )


def infer_trading_sessions_from_parquet(
    path: str | Path,
    *,
    product_name: str | None = None,
    min_day_ratio: float = 0.5,
) -> ObservedTradingSessions:
    source = Path(path)
    frame = pd.read_parquet(source, columns=["trade_time", "trading_day"])
    return infer_trading_sessions(
        frame,
        product_name=product_name or source.stem,
        min_day_ratio=min_day_ratio,
        source_mtime_ns=source.stat().st_mtime_ns,
    )


def sessions_to_record(sessions: ObservedTradingSessions) -> dict:
    return asdict(sessions)
