"""Bounded OHLCV projection for browser chart ranges."""

from __future__ import annotations

import math
from typing import Any, Mapping


def bounded_ohlcv_rows(
    rows: list[dict[str, Any]], request: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """Aggregate contiguous bars without corrupting OHLCV semantics."""
    total = len(rows)
    try:
        maximum = min(5000, max(100, int(request.get("max_points") or 1200)))
    except (TypeError, ValueError):
        maximum = 1200
    if total <= maximum:
        return rows, total
    width = math.ceil(total / maximum)
    sampled: list[dict[str, Any]] = []
    for offset in range(0, total, width):
        bucket = rows[offset:offset + width]
        first, last = bucket[0], bucket[-1]
        entry = {
            **last,
            "timestamp": first.get("timestamp"),
            "time": first.get("time", last.get("time")),
            "open": first.get("open"),
            "high": max(float(item["high"]) for item in bucket),
            "low": min(float(item["low"]) for item in bucket),
            "close": last.get("close"),
            "volume": sum(float(item.get("volume") or 0) for item in bucket),
        }
        if any("open_interest" in item for item in bucket):
            entry["open_interest"] = last.get("open_interest")
        sampled.append(entry)
    return sampled, total
