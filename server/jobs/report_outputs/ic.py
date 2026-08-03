"""Normalize IC Job results for chart and table artifact builders."""

from __future__ import annotations

from typing import Any


def ic_series(result: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for factor in result.get("factors") or ():
        if not isinstance(factor, dict):
            continue
        alias = str(factor.get("factor_alias") or factor.get("alias") or "")
        factor_ref = str(factor.get("factor_ref") or "")
        method = str(factor.get("ic_method") or "rank")
        series_items = factor.get("ic_series_by_forward_horizon") or ()
        if not series_items and isinstance(factor.get("ic_series"), dict):
            series_items = [{
                **factor["ic_series"],
                "horizon": factor.get("primary_forward_return_horizon") or "",
                "entry_delay_bars": 0,
            }]
        for item in series_items:
            if not isinstance(item, dict):
                continue
            dates = list(item.get("dates") or ())
            values = list(item.get("values") or ())
            if not dates or len(dates) != len(values):
                continue
            horizon = str(item.get("horizon") or "")
            delay = int(item.get("entry_delay_bars") or 0)
            output.append({
                "label": f"{alias} · {method} · {horizon} · delay={delay}",
                "factor_alias": alias,
                "factor_ref": factor_ref,
                "ic_method": method,
                "forward_return_horizon": horizon,
                "entry_delay_bars": delay,
                "timestamps": dates,
                "values": values,
            })
    return output


def ic_statistics_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for factor in result.get("factors") or ():
        if not isinstance(factor, dict):
            continue
        alias = str(factor.get("factor_alias") or factor.get("alias") or "")
        factor_ref = str(factor.get("factor_ref") or "")
        method = str(factor.get("ic_method") or "rank")
        half_life = factor.get("forward_ic_half_life") or {}
        for horizon, by_delay in (
            factor.get("ic_stats_by_forward_horizon") or {}
        ).items():
            if not isinstance(by_delay, dict):
                continue
            for delay, stats in by_delay.items():
                if not isinstance(stats, dict):
                    continue
                rows.append({
                    "factor_alias": alias,
                    "factor_ref": factor_ref,
                    "ic_method": method,
                    "forward_return_horizon": str(horizon),
                    "entry_delay_bars": int(delay),
                    "mean_ic": stats.get("mean"),
                    "std": stats.get("std"),
                    "ir": stats.get("IR"),
                    "t_stat": stats.get("t_stat"),
                    "minimum": stats.get("min"),
                    "maximum": stats.get("max"),
                    "ac1": stats.get("ac1"),
                    "ic_series_acf_half_life": stats.get(
                        "ic_series_acf_half_life"
                    ),
                    "forward_ic_half_life_status": half_life.get("status"),
                    "forward_ic_half_life_duration": half_life.get("duration"),
                })
    return rows
