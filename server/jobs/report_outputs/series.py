"""Equity-series extraction and rolling metric calculations."""

from __future__ import annotations

import math
from typing import Any


def extract_series(result: dict[str, Any], source: dict[str, Any]) -> list[dict[str, Any]]:
    groups = result.get("groups") if isinstance(result.get("groups"), list) else []
    if not groups:
        engine = source.get("engine_result") or {}
        for label, portfolio in (engine.get("portfolios") or {}).items():
            if not isinstance(portfolio, dict):
                continue
            curve = portfolio.get("display_equity_curve") or portfolio.get("equity_curve") or {}
            if isinstance(curve, dict):
                groups.append({"name": label, "timestamps": list(curve), "total_equity": list(curve.values())})
    series = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict) or not isinstance(group.get("total_equity"), list):
            continue
        raw_values = group["total_equity"]
        if len(raw_values) < 2:
            continue
        try:
            values = [float(value) for value in raw_values]
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in values):
            continue
        timestamps = group.get("timestamps")
        timestamps = timestamps if isinstance(timestamps, list) else list(range(len(values)))
        series.append({
            "label": str(group.get("name") or group.get("key") or f"Group {index + 1}")[:80],
            "timestamps": timestamps[:len(values)], "values": values,
        })
    return series


def return_series(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "label": item["label"], "timestamps": item["timestamps"],
        "values": [value / (item["values"][0] or 1.0) - 1.0 for value in item["values"]],
    } for item in series]


def metrics_rows(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in series:
        values = item["values"]
        returns = [0.0] + [after / before - 1.0 if before else 0.0 for before, after in zip(values, values[1:])]
        peak = -math.inf
        for index, (timestamp, value, period_return) in enumerate(zip(item["timestamps"], values, returns)):
            peak = max(peak, value)
            window = returns[max(0, index - 59):index + 1]
            mean = sum(window) / len(window)
            variance = sum((part - mean) ** 2 for part in window) / max(1, len(window) - 1)
            volatility = math.sqrt(variance)
            rows.append({
                "series": item["label"], "timestamp": timestamp, "equity": round(value, 8),
                "period_return": round(period_return, 12),
                "cumulative_return": round(value / (values[0] or 1.0) - 1.0, 12),
                "drawdown": round(value / peak - 1.0 if peak else 0.0, 12),
                "rolling_sharpe_60": round(mean / volatility * math.sqrt(len(window)), 12) if volatility else None,
                "rolling_volatility_60": round(volatility, 12),
            })
    return rows


def finite_number(value: Any) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0
