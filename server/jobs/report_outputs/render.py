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


def render_svg(title: str, series: list[dict[str, Any]], *, percent: bool = False) -> bytes:
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
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><title>{escape(title)}</title><rect width="100%" height="100%" fill="white"/><text x="72" y="34" font-size="20">{escape(title)}</text><line x1="72" y1="400" x2="932" y2="400" stroke="#d1d5db"/>']
    for index, item in enumerate(series[:6]):
        points = " ".join(f"{x(i, len(item['values'])):.2f},{y(float(value)):.2f}" for i, value in enumerate(item["values"]))
        parts.append(f'<polyline fill="none" stroke="{colors[index]}" stroke-width="1.7" points="{points}"/><text x="{72 + index * 150}" y="450" font-size="12" fill="{colors[index]}">{escape(item["label"])}</text>')
    suffix = "%" if percent else ""
    parts.append(f'<text x="8" y="84" font-size="11">{high:.5g}{suffix}</text><text x="8" y="400" font-size="11">{low:.5g}{suffix}</text></svg>')
    return "".join(parts).encode("utf-8")
