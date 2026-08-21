"""Post-replay return and drawdown table projections."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def period_return_rows(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in series:
        for frequency in ("month", "year"):
            buckets: dict[str, list[tuple[Any, float]]] = {}
            for timestamp, value in zip(item["timestamps"], item["values"]):
                dt = _datetime(timestamp)
                key = dt.strftime("%Y-%m") if frequency == "month" else dt.strftime("%Y")
                buckets.setdefault(key, []).append((timestamp, value))
            previous_close = item["values"][0] if item["values"] else None
            for period, points in buckets.items():
                start, end = points[0], points[-1]
                rows.append({
                    "strategy_id": item.get("strategy_id", ""),
                    "strategy_configuration_id": item.get("strategy_configuration_id", ""),
                    "series": item["label"], "frequency": frequency,
                    "period": period, "start_timestamp": start[0],
                    "end_timestamp": end[0], "start_value": start[1],
                    "end_value": end[1],
                    # Calendar-period performance includes the move from the
                    # previous period's close to this period's first point.
                    # Using this period's first observation as the denominator
                    # silently dropped every month/year boundary return.
                    "return": (
                        end[1] / previous_close - 1.0
                        if previous_close else None
                    ),
                    "observations": len(points),
                })
                previous_close = end[1]
    return rows


def drawdown_episode_rows(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in series:
        peak_value = float("-inf")
        peak_timestamp = None
        active = None
        for timestamp, value in zip(item["timestamps"], item["values"]):
            if value >= peak_value:
                if active is not None:
                    rows.append(_close_episode(item, active, timestamp, True))
                    active = None
                peak_value = value
                peak_timestamp = timestamp
                continue
            drawdown = value / peak_value - 1.0 if peak_value else 0.0
            if active is None:
                active = {
                    "peak_timestamp": peak_timestamp, "peak_value": peak_value,
                    "trough_timestamp": timestamp, "trough_value": value,
                    "depth": drawdown, "observations": 1,
                }
            else:
                active["observations"] += 1
                if drawdown < active["depth"]:
                    active.update({
                        "trough_timestamp": timestamp, "trough_value": value,
                        "depth": drawdown,
                    })
        if active is not None:
            rows.append(_close_episode(item, active, None, False))
    return rows


def _close_episode(item: dict[str, Any], active: dict[str, Any], recovered_at: Any, recovered: bool):
    return {
        "strategy_id": item.get("strategy_id", ""),
        "strategy_configuration_id": item.get("strategy_configuration_id", ""),
        "series": item["label"], **active,
        "recovered": recovered, "recovery_timestamp": recovered_at,
    }


def _datetime(value: Any) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if abs(number) > 20_000_000_000:
            number /= 1_000.0
        return datetime.fromtimestamp(number, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)
