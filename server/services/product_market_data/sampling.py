"""Bounded OHLCV projection for browser chart ranges."""

from __future__ import annotations

import math
from bisect import bisect_left
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
