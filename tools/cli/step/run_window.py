"""Compact, lossless projections for run-window audit values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .values import scalar, table_from_mappings


def render(field: str, value: Any, *, indent: str) -> list[str] | None:
    if field.endswith(".strategy_windows") and isinstance(value, Mapping):
        rows = []
        for strategy, window in value.items():
            if not isinstance(window, Mapping):
                return None
            rows.append({
                "strategy": strategy,
                "start": _datatime(window.get("start_dt")),
                "end": _datatime(window.get("end_dt")),
                "warmup": scalar(window.get("warmup_window")),
            })
        return table_from_mappings(rows, indent=indent)
    if field.endswith(".run_window_envelope") and isinstance(value, list) and len(value) == 2:
        return table_from_mappings([
            {"boundary": "start", "value": _datatime(value[0])},
            {"boundary": "end", "value": _datatime(value[1])},
        ], indent=indent)
    return None


def _datatime(value: Any) -> str:
    if not isinstance(value, Mapping):
        return scalar(value)
    timestamp = str(value.get("ts") or "")
    precision = str(value.get("precision") or "")
    return f"{timestamp} ({precision})" if precision else timestamp
