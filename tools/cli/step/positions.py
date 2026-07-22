"""PositionBook initialization and delta projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import click

from .values import route_label, table_from_mappings


def render_initialization(rows: list[Mapping[str, Any]], *, indent: str) -> list[str] | None:
    if not rows or not all(row.get("before") is None and isinstance(row.get("after"), Mapping) for row in rows):
        return None
    summaries = []
    for row in rows:
        book = row["after"]
        nonzero = [
            instrument for instrument, position in book.items()
            if isinstance(position, Mapping) and float(position.get("quantity") or 0) != 0
        ]
        summaries.append({
            "owner": route_label(row), "instruments": len(book),
            "nonzero": len(nonzero), "state": "empty" if not nonzero else "active",
        })
    return [
        *table_from_mappings(summaries, indent=indent),
        click.style(f"{indent}空仓初始化未展开逐品种零值；可用 job step-field 查看完整 PositionBook。", dim=True),
    ]
