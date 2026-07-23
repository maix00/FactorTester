"""Small deterministic report image derived from terminal backtest results."""

from __future__ import annotations

from html import escape
import math
from typing import Any

import orjson


SCHEMA_VERSION = 1
RENDERER_VERSION = "equity-svg@1"
MAX_SERIES = 6
MAX_POINTS_PER_SERIES = 800
_COLORS = ("#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2")


def build_equity_curve_artifact(
    result: dict[str, Any],
) -> tuple[bytes, dict[str, Any]] | None:
    """Return an SVG plus receipt, or None when no valid equity series exists."""
    series = _extract_series(result)
    if not series:
        return None
    prepared = []
    for index, item in enumerate(series[:MAX_SERIES]):
        equity_points = _minmax_points(item["values"], MAX_POINTS_PER_SERIES)
        peak = -math.inf
        drawdowns = []
        for value in item["values"]:
            peak = max(peak, value)
            drawdowns.append((value / peak - 1.0) if peak > 0 else 0.0)
        prepared.append({
            "label": item["label"],
            "start": item["start"],
            "end": item["end"],
            "original_points": len(item["values"]),
            "equity_points": equity_points,
            "drawdown_points": _minmax_points(
                drawdowns, MAX_POINTS_PER_SERIES
            ),
            "color": _COLORS[index],
        })
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "equity_curve_report",
        "renderer_version": RENDERER_VERSION,
        "value_basis": "reported_total_equity",
        "x_axis": "observation_order",
        "panels": ["equity", "drawdown"],
        "downsampling": "bucket_minmax_preserve_endpoints",
        "max_points_per_series": MAX_POINTS_PER_SERIES,
        "series": [{
            "label": item["label"],
            "start": item["start"],
            "end": item["end"],
            "original_points": item["original_points"],
            "rendered_points": max(
                len(item["equity_points"]),
                len(item["drawdown_points"]),
            ),
        } for item in prepared],
        "omitted_series_count": max(len(series) - len(prepared), 0),
    }
    return _render_svg(prepared, receipt), receipt


def receipt_bytes(receipt: dict[str, Any]) -> bytes:
    return orjson.dumps(receipt, option=orjson.OPT_SORT_KEYS)


def _extract_series(result: dict[str, Any]) -> list[dict[str, Any]]:
    groups = result.get("groups")
    if not isinstance(groups, list):
        groups = _top_level_groups(result)
    output = []
    for index, raw in enumerate(groups):
        if not isinstance(raw, dict):
            continue
        timestamps = raw.get("timestamps")
        values = raw.get("total_equity")
        if not isinstance(values, list) or len(values) < 2:
            continue
        finite = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                finite = []
                break
            number = float(value)
            if not math.isfinite(number):
                finite = []
                break
            finite.append(number)
        if len(finite) < 2:
            continue
        label = str(
            raw.get("name") or raw.get("key") or raw.get("factor_alias")
            or f"Group {index + 1}"
        )[:80]
        timeline = timestamps if isinstance(timestamps, list) else []
        output.append({
            "label": label,
            "values": finite,
            "start": str(timeline[0])[:64] if timeline else "",
            "end": str(timeline[min(len(timeline), len(finite)) - 1])[:64]
            if timeline else "",
        })
    return output


def _top_level_groups(result: dict[str, Any]) -> list[dict[str, Any]]:
    curve = result.get("equity_curve")
    if isinstance(curve, dict):
        return [{
            "name": "Equity",
            "timestamps": list(curve),
            "total_equity": list(curve.values()),
        }]
    if isinstance(curve, list):
        return [{
            "name": "Equity",
            "timestamps": list(range(len(curve))),
            "total_equity": curve,
        }]
    curves = result.get("curves")
    if isinstance(curves, dict):
        groups = []
        for label, values in curves.items():
            if isinstance(values, dict):
                groups.append({
                    "name": str(label),
                    "timestamps": list(values),
                    "total_equity": list(values.values()),
                })
            elif isinstance(values, list):
                groups.append({
                    "name": str(label),
                    "timestamps": list(range(len(values))),
                    "total_equity": values,
                })
        return groups
    return []


def _minmax_points(values: list[float], maximum: int) -> list[tuple[int, float]]:
    count = len(values)
    if count <= maximum:
        return list(enumerate(values))
    bucket_count = max(1, (maximum - 2) // 2)
    interior = count - 2
    indices = {0, count - 1}
    for bucket in range(bucket_count):
        start = 1 + interior * bucket // bucket_count
        end = 1 + interior * (bucket + 1) // bucket_count
        if end <= start:
            continue
        window = range(start, end)
        minimum = min(window, key=values.__getitem__)
        maximum_index = max(window, key=values.__getitem__)
        indices.update((minimum, maximum_index))
    return [(index, values[index]) for index in sorted(indices)]


def _render_svg(
    series: list[dict[str, Any]], receipt: dict[str, Any]
) -> bytes:
    width, height = 960, 540
    left, right = 72.0, 24.0
    equity_top, equity_bottom = 62.0, 330.0
    drawdown_top, drawdown_bottom = 386.0, 490.0
    plot_width = width - left - right
    all_values = [
        value for item in series for _, value in item["equity_points"]
    ]
    value_min, value_max = min(all_values), max(all_values)
    if value_max == value_min:
        value_max = value_min + 1.0

    def x(index: int, count: int) -> float:
        return left + plot_width * index / max(count - 1, 1)

    def y_equity(value: float) -> float:
        return equity_bottom - (
            (value - value_min) / (value_max - value_min)
        ) * (equity_bottom - equity_top)

    def y_drawdown(value: float) -> float:
        bounded = max(-1.0, min(0.0, value))
        return drawdown_top + (-bounded) * (drawdown_bottom - drawdown_top)

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540" role="img">',
        "<title>净值曲线与回撤</title>",
        "<metadata>" + escape(orjson.dumps(receipt, option=orjson.OPT_SORT_KEYS).decode()) + "</metadata>",
        '<rect width="960" height="540" fill="#ffffff"/>',
        '<g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" fill="#111827">',
        '<text x="72" y="32" font-size="20" font-weight="600">净值曲线</text>',
        '<text x="72" y="374" font-size="15" font-weight="600">回撤</text>',
        f'<line x1="{left}" y1="{equity_bottom}" x2="{width-right}" y2="{equity_bottom}" stroke="#d1d5db"/>',
        f'<line x1="{left}" y1="{drawdown_top}" x2="{width-right}" y2="{drawdown_top}" stroke="#d1d5db"/>',
        f'<line x1="{left}" y1="{drawdown_bottom}" x2="{width-right}" y2="{drawdown_bottom}" stroke="#d1d5db"/>',
    ]
    legend_x = left
    for item in series:
        count = item["original_points"]
        equity_points = " ".join(
            f"{x(index, count):.2f},{y_equity(value):.2f}"
            for index, value in item["equity_points"]
        )
        drawdown_points = " ".join(
            f"{x(index, count):.2f},{y_drawdown(value):.2f}"
            for index, value in item["drawdown_points"]
        )
        color = item["color"]
        parts.extend([
            f'<polyline fill="none" stroke="{color}" stroke-width="1.7" points="{equity_points}"/>',
            f'<polyline fill="none" stroke="{color}" stroke-width="1.3" points="{drawdown_points}"/>',
            f'<line x1="{legend_x}" y1="520" x2="{legend_x+18}" y2="520" stroke="{color}" stroke-width="3"/>',
            f'<text x="{legend_x+23}" y="525" font-size="12">{escape(item["label"])}</text>',
        ])
        legend_x += min(190, 45 + len(item["label"]) * 7)
    parts.extend([
        f'<text x="8" y="{equity_top+5}" font-size="11">{value_max:.4g}</text>',
        f'<text x="8" y="{equity_bottom}" font-size="11">{value_min:.4g}</text>',
        f'<text x="28" y="{drawdown_top+5}" font-size="11">0%</text>',
        f'<text x="18" y="{drawdown_bottom}" font-size="11">-100%</text>',
        "</g></svg>",
    ])
    return "".join(parts).encode("utf-8")
