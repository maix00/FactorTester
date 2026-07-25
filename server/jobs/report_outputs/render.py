"""Deterministic JSON, CSV and compact SVG encoders."""

from __future__ import annotations

import csv
from html import escape
import io
import json
from typing import Any


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")


def csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    columns = sorted({key for row in rows for key in row if key != "raw"})
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns or ["empty"])
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key) for key in writer.fieldnames})
    return output.getvalue().encode("utf-8-sig")


def render_svg(
    title: str,
    series: list[dict[str, Any]],
    *,
    percent: bool = False,
    initial_value: float | None = None,
) -> bytes:
    width, height = 960, 480
    values = [float(value) for item in series for value in item["values"]]
    if not values:
        return b""
    low, high = min(values), max(values)
    if low == high:
        high = low + 1.0
    colors = ("#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2")
    def x(index, count): return 72 + 860 * index / max(1, count - 1)
    def y(value): return 400 - 320 * (value - low) / (high - low)
    def display(value): return f"{value * 100:.4g}%" if percent else f"{value:.5g}"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><title>{escape(title)}</title><rect width="100%" height="100%" fill="white"/><text x="72" y="34" font-size="20">{escape(title)}</text>',
    ]
    for tick in range(5):
        value = low + (high - low) * tick / 4
        y_position = y(value)
        parts.append(
            f'<line x1="72" y1="{y_position:.2f}" x2="932" y2="{y_position:.2f}" stroke="#e5e7eb"/>'
            f'<text x="8" y="{y_position + 4:.2f}" font-size="11">{display(value)}</text>'
        )
    if initial_value is not None and low <= initial_value <= high:
        y_position = y(initial_value)
        parts.append(
            f'<line x1="72" y1="{y_position:.2f}" x2="932" y2="{y_position:.2f}" stroke="#6b7280" stroke-dasharray="5,4"/>'
            f'<text x="740" y="{y_position - 5:.2f}" font-size="11" fill="#4b5563">初始金额 {display(initial_value)}</text>'
        )
    for index, item in enumerate(series[:6]):
        points = " ".join(f"{x(i, len(item['values'])):.2f},{y(float(value)):.2f}" for i, value in enumerate(item["values"]))
        parts.append(f'<polyline fill="none" stroke="{colors[index]}" stroke-width="1.7" points="{points}"/><text x="{72 + index * 150}" y="450" font-size="12" fill="{colors[index]}">{escape(item["label"])}</text>')
        timestamps = item.get("timestamps") or []
        for tick in _axis_indices(len(item["values"])):
            if tick < len(timestamps):
                parts.append(
                    f'<line x1="{x(tick, len(item["values"])):.2f}" y1="400" x2="{x(tick, len(item["values"])):.2f}" y2="406" stroke="#9ca3af"/>'
                    f'<text x="{x(tick, len(item["values"])):.2f}" y="420" text-anchor="middle" font-size="10">{escape(_timestamp_label(timestamps[tick]))}</text>'
                )
    parts.append("</svg>")
    return "".join(parts).encode("utf-8")


def render_metrics_svg(title: str, series: list[dict[str, Any]]) -> bytes:
    """Render cumulative/rolling metrics as separate readable panels."""
    metrics = list(dict.fromkeys(str(item.get("metric") or "") for item in series if item.get("metric")))
    if not metrics:
        return b""
    width, panel_height, left, right = 960, 190, 86, 28
    height = 48 + panel_height * len(metrics)
    colors = ("#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><title>{escape(title)}</title><rect width="100%" height="100%" fill="white"/><text x="{left}" y="30" font-size="20">{escape(title)}</text>'
    ]
    for metric_index, metric in enumerate(metrics):
        items = [item for item in series if item.get("metric") == metric and item.get("values")]
        if not items:
            continue
        top = 48 + metric_index * panel_height + 28
        bottom = top + 112
        low = min(float(value) for item in items for value in item["values"])
        high = max(float(value) for item in items for value in item["values"])
        if low == high:
            low, high = low - 0.5, high + 0.5
        def x(index: int, count: int) -> float:
            return left + (width - left - right) * index / max(1, count - 1)
        def y(value: float) -> float:
            return bottom - (bottom - top) * (value - low) / (high - low)
        label = str(items[0].get("metric_label") or metric)
        parts.append(f'<text x="{left}" y="{top - 10}" font-size="14" font-weight="600">{escape(label)}</text>')
        for tick in range(4):
            value = low + (high - low) * tick / 3
            position = y(value)
            parts.append(
                f'<line x1="{left}" y1="{position:.2f}" x2="{width-right}" y2="{position:.2f}" stroke="#e5e7eb"/>'
                f'<text x="8" y="{position + 4:.2f}" font-size="10">{_metric_axis_value(metric, value)}</text>'
            )
        for item_index, item in enumerate(items[:6]):
            color = colors[item_index % len(colors)]
            values = [float(value) for value in item["values"]]
            points = " ".join(f"{x(index, len(values)):.2f},{y(value):.2f}" for index, value in enumerate(values))
            parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="1.6" points="{points}"/>')
            parts.append(f'<text x="{left + item_index * 150}" y="{bottom + 27}" font-size="11" fill="{color}">{escape(str(item.get("label") or ""))}</text>')
        timestamps = items[0].get("timestamps") or []
        for index in _axis_indices(len(items[0]["values"])):
            if index >= len(timestamps):
                continue
            position = x(index, len(items[0]["values"]))
            parts.append(f'<line x1="{position:.2f}" y1="{bottom}" x2="{position:.2f}" y2="{bottom + 5}" stroke="#9ca3af"/><text x="{position:.2f}" y="{bottom + 43}" text-anchor="middle" font-size="10">{escape(_timestamp_label(timestamps[index]))}</text>')
    parts.append("</svg>")
    return "".join(parts).encode("utf-8")


def _axis_indices(count: int) -> list[int]:
    if count <= 1:
        return [0] if count else []
    return sorted(set([0, count // 4, count // 2, (count * 3) // 4, count - 1]))


def _timestamp_label(value: Any) -> str:
    text = str(value)
    return text.replace("T", " ")[:16]


def _metric_axis_value(metric: str, value: float) -> str:
    if metric in {"annual_return", "max_drawdown", "drawdown", "rolling_volatility_60"}:
        return f"{value * 100:.3g}%"
    return f"{value:.3g}"
