"""Shared sample clipping helpers for audit formatter output."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AuditSamplePart:
    name: str
    value: Any


def select_sample_part(sample: dict[str, Any], predicate: Callable[[Any], bool]) -> AuditSamplePart | None:
    """Pick one representative sample block; prefer head, fall back to tail."""
    for name in ("head", "tail"):
        value = sample.get(name)
        if predicate(value):
            return AuditSamplePart(name=name, value=value)
    return None


def sample_note_lines(sample: dict[str, Any], selected_name: str) -> list[str]:
    other_name = "tail" if selected_name == "head" else "head"
    if other_name in sample:
        return [f"sample = 仅显示 {selected_name}；{other_name} 已省略"]
    return []


def single_sample_sequence(items: list[Any]) -> tuple[list[Any], list[str]]:
    if len(items) <= 1:
        return items, []
    return items[:1], [f"sample.rows = 仅显示 1/{len(items)} 行；其余 sample 行已省略"]


def single_sample_frame(frame: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    indexes = frame.get("index")
    rows = frame.get("rows")
    if not isinstance(indexes, list) or not isinstance(rows, list) or len(rows) <= 1:
        return frame, []
    clipped = dict(frame)
    clipped["index"] = indexes[:1]
    clipped["rows"] = rows[:1]
    return clipped, [f"sample.rows = 仅显示 1/{len(rows)} 行；其余 sample 行已省略"]


def single_sample_series(series: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    indexes = series.get("index")
    values = series.get("values")
    if not isinstance(indexes, list) or not isinstance(values, list) or len(values) <= 1:
        return series, []
    clipped = dict(series)
    clipped["index"] = indexes[:1]
    clipped["values"] = values[:1]
    return clipped, [f"sample.rows = 仅显示 1/{len(values)} 行；其余 sample 行已省略"]
