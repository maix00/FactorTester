"""Equity-series extraction and rolling metric calculations."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def extract_series(result: dict[str, Any], source: dict[str, Any]) -> list[dict[str, Any]]:
    groups = result.get("groups") if isinstance(result.get("groups"), list) else []
    # Small runners and registration adapters may return one bare equity list rather
    # than the grouped backtest envelope.  Treat it as the single default
    # series so the same report/evidence contract still applies.
    if not groups and isinstance(result.get("equity_curve"), list):
        groups = [{
            "name": "equity",
            "timestamps": list(range(len(result["equity_curve"]))),
            "total_equity": list(result["equity_curve"]),
        }]
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
            "strategy_id": str(group.get("strategy_id") or group.get("group_id") or ""),
            "strategy_configuration_id": str(
                group.get("strategy_configuration_id") or ""
            ),
            "label": str(
                group.get("display_name")
                or group.get("name")
                or group.get("strategy_id")
                or group.get("group_id")
                or f"Group {index + 1}"
            )[:80],
            "timestamps": timestamps[:len(values)], "values": values,
            "currency": str(group.get("base_currency") or "CNY").upper(),
        })
    return series


def return_series(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "strategy_id": item.get("strategy_id", ""),
        "strategy_configuration_id": item.get("strategy_configuration_id", ""),
        "label": item["label"], "timestamps": item["timestamps"],
        "values": [value / (item["values"][0] or 1.0) - 1.0 for value in item["values"]],
        "currency": item.get("currency", ""),
    } for item in series]


def metrics_rows(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in series:
        values = item["values"]
        returns = [0.0] + [after / before - 1.0 if before else 0.0 for before, after in zip(values, values[1:])]
        peak = -math.inf
        historical_max_drawdown = 0.0
        initial = values[0]
        for index, (timestamp, value, period_return) in enumerate(zip(item["timestamps"], values, returns)):
            peak = max(peak, value)
            current_drawdown = value / peak - 1.0 if peak else 0.0
            historical_max_drawdown = min(historical_max_drawdown, current_drawdown)
            window = returns[max(0, index - 59):index + 1]
            mean = sum(window) / len(window)
            variance = sum((part - mean) ** 2 for part in window) / max(1, len(window) - 1)
            volatility = math.sqrt(variance)
            sharpe = mean / volatility * math.sqrt(len(window)) if volatility else None
            rows.append({
                "strategy_id": item.get("strategy_id", ""),
                "strategy_configuration_id": item.get("strategy_configuration_id", ""),
                "series": item["label"], "timestamp": timestamp, "equity": round(value, 8),
                "period_return": round(period_return, 12),
                "cumulative_return": round(value / (values[0] or 1.0) - 1.0, 12),
                "drawdown": round(current_drawdown, 12),
                "max_drawdown": round(historical_max_drawdown, 12),
                "annual_return": round(_annual_return(initial, value, item["timestamps"][0], timestamp), 12),
                "sharpe_ratio": round(sharpe, 12) if sharpe is not None else None,
                "rolling_sharpe_60": round(mean / volatility * math.sqrt(len(window)), 12) if volatility else None,
                "rolling_volatility_60": round(volatility, 12),
            })
    return rows


def _annual_return(initial: float, value: float, start: Any, end: Any) -> float:
    if initial <= 0 or value <= 0:
        return 0.0
    start_seconds = _timestamp_seconds(start)
    end_seconds = _timestamp_seconds(end)
    elapsed_days = (end_seconds - start_seconds) / 86_400.0
    # Observation-order indexes (0, 1, 2, …) are not calendar timestamps;
    # annualizing over a few seconds would produce meaningless overflow.
    if elapsed_days < 1.0:
        return 0.0
    exponent = min(365.25 / elapsed_days, 1_000.0)
    try:
        result = (value / initial) ** exponent - 1.0
    except OverflowError:
        result = math.copysign(float("1e308"), value - initial)
    return result if math.isfinite(result) else math.copysign(float("1e308"), result)


def _timestamp_seconds(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        return number / 1_000.0 if abs(number) > 20_000_000_000 else number
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return 0.0


def finite_number(value: Any) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0
