"""Runtime configuration helpers for backtest execution."""

from __future__ import annotations

from typing import Any


def equity_curve_live_enabled(store) -> bool:
    curve_mode = store.effective("equity_curve_mode")
    if curve_mode is not None:
        return str(curve_mode).strip().lower() == "live"
    return truthy(store.effective("equity_compute_live"))


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y", "on", "live"}
