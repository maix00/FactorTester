"""Minimal retained source and lazy strategy-analysis projections."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .detail import (
    _build_calendar_analysis,
    _build_capacity_analysis,
    _build_daily_analysis,
    _build_explanations,
    _build_holding_analysis,
    _build_intraday_analysis,
    _build_period_robustness,
    _build_positive_run_analysis,
    _build_robustness_summary,
    _build_rolling_analysis,
)
from .monotonicity import build_group_ranking_detail

ARTIFACT_VERSION = 1

_DETAIL_KEYS = {
    "overview": "summary",
    "membership": "entry_frequency",
    "distribution": "distribution",
    "rolling": "rolling_analysis",
    "capacity": "capacity_analysis",
    "tradability": "tradability_analysis",
    "calendar": "calendar_analysis",
    "holding": "holding_analysis",
    "explanations": "explanations",
    "products": "product_analysis",
    "daily": "daily_analysis",
    "positive_runs": "positive_run_analysis",
    "intraday": "intraday_analysis",
}

STRATEGY_ANALYSIS_TABS = frozenset({
    *_DETAIL_KEYS,
    "robustness", "periods", "positive_runs", "intraday",
})


def _strategy_id(owner: dict[str, Any]) -> str:
    return str(owner.get("strategy_id") or owner.get("group_id") or "")


def build_strategy_analysis_source(
    execution: dict[str, Any], serialized: dict[str, Any],
) -> dict[str, Any]:
    """Retain only primitives unavailable from the bounded result summary.

    Analysis tables and charts are deliberately absent.  The source Manager
    computes one requested tab on first access and returns only that payload.
    """
    engine_result = execution.get("engine_result") or {}
    portfolios = engine_result.get("portfolios") or {}
    groups = {
        str(item.get("strategy_id") or item.get("group_id") or ""): dict(item)
        for item in serialized.get("groups") or ()
        if str(item.get("strategy_id") or item.get("group_id") or "")
    }
    strategies: dict[str, Any] = {}
    for owner in execution.get("group_owner") or ():
        strategy_id = _strategy_id(owner)
        if not strategy_id:
            continue
        portfolio = portfolios.get(strategy_id) or {}
        strategies[strategy_id] = {
            "identity": dict(owner),
            "result_group": groups.get(strategy_id) or {},
            "position_curve": portfolio.get("position_curve") or {},
            "notional_curve": portfolio.get("notional_curve") or {},
            "margin_curve": portfolio.get("margin_curve") or {},
            "fill_turnover": portfolio.get("fill_turnover") or {},
        }
    detail_context = execution.get("detail_context") or {}
    return {
        "artifact_version": ARTIFACT_VERSION,
        "engine": str(engine_result.get("engine") or ""),
        "strategies": strategies,
        "metrics": dict(serialized.get("metrics") or {}),
        "detail_context": {
            "payload": dict(
                execution.get("payload")
                or detail_context.get("payload")
                or {}
            ),
            "settings_by_strategy": dict(
                execution.get("settings_by_strategy")
                or detail_context.get("settings_by_strategy")
                or {}
            ),
        },
    }


def _curve(row: dict[str, Any]) -> pd.Series:
    group = row.get("result_group") or {}
    timestamps = list(group.get("timestamps") or ())
    equities = list(group.get("total_equity") or ())
    if timestamps and len(timestamps) == len(equities):
        index = pd.to_datetime(timestamps, unit="ms", utc=True)
        return pd.Series([float(value) for value in equities], index=index)
    raw = row.get("equity_curve") or {}
    if not raw:
        return pd.Series(dtype=float)
    return pd.Series(
        [float(value) for value in raw.values()],
        index=pd.DatetimeIndex([pd.Timestamp(value) for value in raw]),
    ).sort_index()


def _return_series(curve: pd.Series) -> list[dict[str, Any]]:
    returns = curve.pct_change().fillna(0.0)
    wealth = 1.0
    rows = []
    for timestamp, value in returns.items():
        number = float(value)
        wealth *= 1.0 + number
        rows.append({
            "timestamp": pd.Timestamp(timestamp).isoformat(),
            "return": number,
            "cumulative_return": wealth,
        })
    return rows


def _products_by_timestamp(row: dict[str, Any], curve: pd.Series) -> dict[Any, list[str]]:
    positions = row.get("position_curve") or {}
    result = {}
    for timestamp in curve.index:
        values = _time_mapping_value(positions, timestamp) or {}
        result[timestamp] = [
            str(product) for product, quantity in (values or {}).items()
            if abs(float(quantity)) > 1e-12
        ]
    return result


def _time_mapping_value(mapping: dict[Any, Any], timestamp: Any) -> Any:
    """Read live Timestamp keys and their retained JSON string forms."""
    stamp = pd.Timestamp(timestamp)
    candidates = (
        timestamp, stamp, stamp.isoformat(), str(stamp),
        stamp.tz_convert("UTC").isoformat() if stamp.tzinfo else "",
        str(int(stamp.timestamp() * 1000)),
    )
    for key in candidates:
        if key != "" and key in mapping:
            return mapping[key]
    return None


def _entry_frequency(products: dict[Any, list[str]], total: int) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for values in products.values():
        for product in values:
            counts[product] = counts.get(product, 0) + 1
    return [
        {
            "product": {"name": product, "desc": product},
            "count": count,
            "frequency": count / max(total, 1),
            "mean_return": None,
        }
        for product, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0]),
        )
    ]


def _distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = np.asarray([row["return"] for row in rows], dtype=float)
    values = values[np.isfinite(values)]
    if not values.size:
        return {"histogram": [], "quantiles": {}, "period_count": 0}
    counts, edges = np.histogram(
        values, bins=min(20, max(5, int(np.sqrt(values.size)))),
    )
    return {
        "histogram": [
            {"left": float(edges[index]), "right": float(edges[index + 1]),
             "count": int(count)}
            for index, count in enumerate(counts)
        ],
        "quantiles": dict(zip(
            ("p05", "p25", "p50", "p75", "p95"),
            map(float, np.quantile(values, [0.05, 0.25, 0.5, 0.75, 0.95])),
        )),
        "period_count": int(values.size),
    }


def _product_analysis(row: dict[str, Any], curve: pd.Series) -> dict[str, Any]:
    positions = row.get("position_curve") or {}
    notionals = row.get("notional_curve") or {}
    totals: dict[str, dict[str, float | int]] = {}
    previous_equity: float | None = None
    for timestamp, equity_value in curve.items():
        equity = float(equity_value)
        period_return = (
            0.0 if previous_equity is None or previous_equity <= 0
            else equity / previous_equity - 1.0
        )
        previous_equity = equity
        position_row = _time_mapping_value(positions, timestamp) or {}
        notional_row = _time_mapping_value(notionals, timestamp) or {}
        active = {
            str(product): abs(float(notional_row.get(product) or quantity))
            for product, quantity in position_row.items()
            if abs(float(quantity)) > 1e-12
        }
        denominator = sum(active.values())
        if denominator <= 0:
            continue
        for product, notional in active.items():
            item = totals.setdefault(product, {"count": 0, "contribution": 0.0})
            item["count"] = int(item["count"]) + 1
            item["contribution"] = float(item["contribution"]) + period_return * notional / denominator
    rows = [{
        "product": {"name": product, "desc": product},
        "active_period_count": int(value["count"]),
        "gross_contribution": float(value["contribution"]),
        "mean_active_contribution": (
            float(value["contribution"]) / int(value["count"])
            if int(value["count"]) else None
        ),
    } for product, value in totals.items()]
    top = sorted(rows, key=lambda item: item["gross_contribution"], reverse=True)
    bottom = list(reversed(top))
    positive = sum(max(item["gross_contribution"], 0.0) for item in rows)
    top1 = top[0]["gross_contribution"] / positive if top and positive > 0 else None
    top3 = sum(max(item["gross_contribution"], 0.0) for item in top[:3]) / positive if positive > 0 else None
    return {
        "rows": rows, "top_products": top[:10], "bottom_products": bottom[:10],
        "top1_positive_contribution_ratio": top1,
        "top3_positive_contribution_ratio": top3,
        "is_concentrated": bool(
            (top1 is not None and top1 >= 0.5)
            or (top3 is not None and top3 >= 0.8)
        ),
    }


def _strategy(source: dict[str, Any], strategy_id: str) -> dict[str, Any]:
    row = (source.get("strategies") or {}).get(strategy_id)
    if not isinstance(row, dict):
        raise ValueError(f"策略分析数据中不存在策略 {strategy_id!r}")
    return row


def _ranking(source: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    configuration_id = str(params.get("strategy_configuration_id") or "")
    selection_id = str(params.get("product_path_selection_id") or "")
    selected = []
    for row in (source.get("strategies") or {}).values():
        identity = row.get("identity") or {}
        if (
            str(identity.get("strategy_configuration_id") or "") == configuration_id
            and str(identity.get("product_path_selection_id") or "") == selection_id
            and not identity.get("is_ls")
        ):
            selected.append(row)
    selected.sort(key=lambda row: int((row.get("identity") or {}).get("group_index") or 0))
    if len(selected) < 2:
        raise ValueError("至少需要两个普通分组才能分析排序能力")
    returns = [item for item in (_curve(row).pct_change().fillna(0.0) for row in selected) if not item.empty]
    if len(returns) < 2:
        raise ValueError("至少需要两条有效策略净值曲线")
    aligned = pd.concat(returns, axis=1, join="inner").sort_index()
    return build_group_ranking_detail(aligned.to_numpy(), list(aligned.index))


def build_strategy_analysis_tab(
    source: dict[str, Any], params: dict[str, Any],
) -> dict[str, Any]:
    """Compute exactly one registered analysis tab from retained primitives."""
    tab = str(params.get("analysis_tab") or params.get("tab") or "overview")
    if tab == "ranking":
        return _ranking(source, params)
    bundle = build_strategy_analysis_bundle(source, params)
    if tab not in bundle:
        raise ValueError(f"unsupported strategy-analysis tab: {tab}")
    return bundle[tab]


def build_strategy_analysis_bundle(
    source: dict[str, Any], params: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build every strategy-local tab from one shared projection.

    Parsing the retained curve and deriving common return/product projections
    dominates these small analyses.  A supplemental task therefore computes
    one strategy bundle and persists independently addressable tab artifacts.
    """
    strategy_id = str(params.get("strategy_id") or params.get("group_id") or "")
    row = _strategy(source, strategy_id)
    curve = _curve(row)
    if curve.empty:
        raise ValueError("所选策略没有可分析的净值曲线")
    returns = _return_series(curve)
    products = _products_by_timestamp(row, curve)
    summary = dict((source.get("metrics") or {}).get(
        str((row.get("result_group") or {}).get("metrics_key") or strategy_id),
        {},
    ))
    timestamps = list(curve.index)
    entry_frequency = _entry_frequency(products, len(curve))
    distribution = _distribution(returns)
    rolling = _build_rolling_analysis(returns)
    capacity = _build_capacity_analysis(products, timestamps)
    turnover = row.get("fill_turnover") or {}
    tradability = {
        "avg_trade_notional_ratio": turnover.get("average"),
        "turnover_observations": int(turnover.get("observations") or 0),
        "turnover_source": str(turnover.get("source") or "unavailable"),
    }
    calendar = _build_calendar_analysis(returns)
    holding = _build_holding_analysis(products, timestamps)
    product = _product_analysis(row, curve)
    daily = _build_daily_analysis(returns)
    positive = _build_positive_run_analysis(returns)
    period = _build_period_robustness(returns)
    periods = [{
        "timestamp": item["timestamp"], "return": item["return"],
        "products": [
            {"name": product_name, "desc": product_name}
            for product_name in products.get(timestamp, [])
        ],
    } for item, timestamp in zip(returns, timestamps)]
    ordered = sorted(periods, key=lambda item: item["return"], reverse=True)
    common = (
        positive, daily, period, product, calendar, holding,
        tradability, capacity, rolling,
    )
    return {
        "overview": {"summary": summary},
        "membership": {"entry_frequency": entry_frequency},
        "distribution": {"distribution": distribution},
        "rolling": {"rolling_analysis": rolling},
        "capacity": {"capacity_analysis": capacity},
        "tradability": {"tradability_analysis": tradability},
        "calendar": {"calendar_analysis": calendar},
        "holding": {"holding_analysis": holding},
        "explanations": {"explanations": _build_explanations(*common)},
        "products": {"product_analysis": product},
        "daily": {"daily_analysis": daily},
        "robustness": {
            "robustness_summary": _build_robustness_summary(*common),
            "period_robustness": period,
        },
        "periods": {
            "top_periods": ordered[:10],
            "bottom_periods": list(reversed(ordered[-10:])),
        },
        "positive_runs": {"positive_run_analysis": positive},
        "intraday": {"intraday_analysis": _build_intraday_analysis(returns)},
    }
