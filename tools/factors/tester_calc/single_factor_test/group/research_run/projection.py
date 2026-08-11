"""Project grouped engine output into the stable research-result contract."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from tools.data.types.time_index import DataIndex


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def _infer_periods_per_year(index_like: Any) -> float:
    index = DataIndex(pd.Index(index_like)).signal_index.dropna()
    if len(index) < 2:
        return 252.0
    per_day = pd.Series(1, index=index.normalize()).groupby(level=0).sum()
    median_per_day = float(per_day.median()) if not per_day.empty else 1.0
    if median_per_day > 1:
        return median_per_day * 252.0
    unique_days = pd.DatetimeIndex(per_day.index).sort_values()
    if len(unique_days) < 2:
        return 252.0
    business_days = np.busday_count(
        unique_days[0].date().isoformat(),
        (unique_days[-1] + pd.Timedelta(days=1)).date().isoformat(),
    )
    if business_days <= 0:
        return 252.0
    return max(1.0, len(unique_days) / business_days * 252.0)


def _compute_return_metrics(
    returns: np.ndarray,
    *,
    index_like: Any = None,
    avg_turnover: Any = None,
) -> dict[str, Any]:
    series = pd.Series(returns).replace([np.inf, -np.inf], np.nan).dropna()
    count = len(series)
    if count == 0:
        return {}
    annual_periods = (
        _infer_periods_per_year(index_like)
        if index_like is not None
        else 252.0
    )
    cumulative = (1 + series).cumprod()
    drawdown = (cumulative.cummax() - cumulative) / cumulative.cummax()
    annual_return = (
        _safe_float((cumulative.iloc[-1] ** (annual_periods / count) - 1) * 100)
        if count > 1
        else None
    )
    max_drawdown = _safe_float(drawdown.max() * 100) if count > 0 else None
    standard_deviation = series.std()
    return {
        "Total Return": _safe_float((cumulative.iloc[-1] - 1) * 100),
        "Annual Return": annual_return,
        "Volatility": _safe_float(standard_deviation * annual_periods**0.5 * 100),
        "Sharpe Ratio": (
            _safe_float(
                (series.mean() * annual_periods)
                / (standard_deviation * annual_periods**0.5)
            )
            if standard_deviation != 0
            else None
        ),
        "Max Drawdown": max_drawdown,
        "Calmar Ratio": (
            _safe_float(float(annual_return) / float(max_drawdown))
            if annual_return and max_drawdown
            else None
        ),
        "Win Rate": _safe_float((series > 0).sum() / count * 100),
        "Mean Return": _safe_float(series.mean() * 100),
        "Skewness": _safe_float(series.skew()),
        "Kurtosis": _safe_float(series.kurtosis()),
        "Avg Turnover": _safe_float(avg_turnover),
    }


def _trace_checksum(trace: Any) -> str | None:
    if not trace:
        return None
    compact_checksum = getattr(trace, "checksum", None)
    if callable(compact_checksum):
        value = compact_checksum()
        if value is not None:
            return value
    digest = hashlib.sha256()
    sorted_rows = getattr(trace, "iter_checksum_rows", None)
    if isinstance(trace, dict):
        rows = [
            {"timestamp": timestamp, "payload": payload or {}}
            for timestamp, payload in trace.items()
        ]
    elif callable(sorted_rows):
        rows = sorted_rows()
    elif isinstance(trace, list):
        rows = [
            row if isinstance(row, dict) else {"payload": row}
            for row in trace
        ]
    else:
        rows = [{"payload": trace}]
    if not callable(sorted_rows):
        rows = sorted(
            rows,
            key=lambda row: (
                str(row.get("timestamp") or ""),
                str(row.get("order_id") or ""),
                str(row.get("step") or ""),
                json.dumps(row, ensure_ascii=False, sort_keys=True, default=str),
            ),
        )
    for row in rows:
        digest.update(str(row.get("timestamp") or "").encode("utf-8"))
        digest.update(b"\0")
        digest.update(json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _serialize_float_series(
    values: np.ndarray | list,
    default: float = 0.0,
) -> list[float]:
    result = []
    for value in values:
        number = _safe_float(value)
        result.append(round(number, 8) if number is not None else default)
    return result


def serialize_event_execution(
    execution: dict[str, Any],
    *,
    settings_by_group: dict[str, dict[str, Any]],
    evaluation_split: str | None,
    registry: Any | None = None,
    group_result: Any = None,
    include_execution_trace_checksums: bool = True,
) -> dict[str, Any]:
    """Convert one framework ledger into the grouped-result contract."""
    engine_result = execution["engine_result"]
    portfolios = engine_result.get("portfolios") or {}
    target_trace = engine_result.get("target_trace") or {}
    diagnostics = engine_result.get("strategy_diagnostics") or {}
    groups = []
    metrics = {}
    metrics_by_segment = {}
    comparison_strategies = []
    split = pd.Timestamp(evaluation_split) if evaluation_split else None
    display_name_counts = Counter(
        str(owner.get("group_name") or owner.get("group_id") or "")
        for owner in execution["group_owner"]
    )

    for owner in execution["group_owner"]:
        strategy_id = str(owner.get("group_id") or "")
        if strategy_id not in portfolios:
            raise ValueError(
                f"{engine_result.get('engine')} result missing portfolio "
                f"{strategy_id!r}; available={sorted(portfolios)}"
            )
        portfolio = portfolios[strategy_id]
        curve = (
            portfolio.get("display_equity_curve")
            or portfolio.get("equity_curve")
            or {}
        )
        index = pd.DatetimeIndex([pd.Timestamp(value) for value in curve])
        equity = np.asarray(
            [float(value) for value in curve.values()],
            dtype=float,
        )
        if len(index) != len(equity) or not len(index):
            raise ValueError(
                f"portfolio {strategy_id!r} returned an empty equity curve"
            )
        returns = pd.Series(equity, index=index).pct_change().fillna(0.0)
        display_name = str(owner.get("group_name") or strategy_id)
        metrics_key = (
            display_name
            if display_name_counts[display_name] == 1
            else strategy_id
        )
        settings = settings_by_group[strategy_id]
        strategy_target_trace = target_trace.get(strategy_id, {})
        execution_trace = portfolio.get("execution_trace") or {}
        comparison_strategies.append({
            "strategy_id": strategy_id,
            "display_name": display_name,
            "final_value": round(float(equity[-1]), 10),
            "equity_points": int(len(equity)),
            "target_trace_points": int(len(strategy_target_trace)),
            "target_trace_checksum": _trace_checksum(strategy_target_trace),
            "execution_trace_points": int(
                portfolio.get("execution_trace_count") or len(execution_trace)
            ),
            "execution_trace_checksum": (
                _trace_checksum(execution_trace)
                if include_execution_trace_checksums
                else None
            ),
            "snapshot_points": int(len(portfolio.get("position_curve") or {})),
        })
        module_outputs: dict[str, Any] = {}
        if registry is not None:
            module_outputs = registry.collect_outputs(
                group_result=group_result,
                owner=owner,
                settings=settings,
            )
        groups.append({
            "key": display_name,
            "name": display_name,
            "group_id": strategy_id,
            "metrics_key": metrics_key,
            "group_index": int(owner.get("group_index") or 0),
            "product_path_selection_id": str(
                owner.get("product_path_selection_id") or ""
            ),
            "factor_alias": str(owner.get("factor_alias") or ""),
            "timestamps": [int(value.timestamp() * 1000) for value in index],
            "total_equity": [round(float(value), 2) for value in equity],
            "gross_returns": _serialize_float_series(returns.to_numpy()),
            "engine": str(engine_result.get("engine") or ""),
            "allocation_policy": settings["allocation_policy"],
            "rebalance_trigger": settings["rebalance_trigger"],
            "position_policy": settings["position_policy"],
            "target_trace_available": bool(strategy_target_trace),
            "strategy_diagnostics": diagnostics.get(strategy_id, {}),
            "snapshot_available": bool(portfolio.get("position_curve")),
            "is_ls": bool(owner.get("is_ls")),
            "ls_info": (
                {"type": "long_short", "strategy_id": strategy_id}
                if owner.get("is_ls")
                else None
            ),
            **module_outputs,
        })
        metrics[metrics_key] = _compute_return_metrics(
            returns.to_numpy(),
            index_like=index,
        )
        if split is not None:
            comparable_split = split
            if index.tz is not None and split.tzinfo is None:
                comparable_split = split.tz_localize(index.tz)
            elif index.tz is None and split.tzinfo is not None:
                comparable_split = split.tz_localize(None)
            in_sample = returns[index <= comparable_split]
            out_of_sample = returns[index > comparable_split]
            metrics_by_segment[metrics_key] = {
                "in_sample": _compute_return_metrics(
                    in_sample.to_numpy(),
                    index_like=in_sample.index,
                ),
                "out_of_sample": _compute_return_metrics(
                    out_of_sample.to_numpy(),
                    index_like=out_of_sample.index,
                ),
                "full": metrics[metrics_key],
            }
    initial_values = [
        float(value.get("initial_value") or 0.0)
        for value in portfolios.values()
    ]
    approximation_count = max(
        (
            int(value.get("market_rule_approximation_count") or 0)
            for value in diagnostics.values()
        ),
        default=0,
    )
    setting_fallbacks = [
        {**dict(item), "strategy_id": strategy_id}
        for strategy_id, value in diagnostics.items()
        for item in (value.get("setting_fallbacks") or [])
        if isinstance(item, dict)
    ]
    return {
        "groups": groups,
        "metrics": metrics,
        "metrics_by_segment": metrics_by_segment,
        "initial_capital": initial_values[0] if initial_values else None,
        "base_currency": "CNY",
        "market_rule_approximation_count": approximation_count,
        "market_rule_warning": (
            f"历史市场规则有 {approximation_count} 个单元格缺失，"
            "已按设置使用最新值或配置默认值近似。"
            if approximation_count
            else None
        ),
        "setting_fallbacks": setting_fallbacks,
        "setting_fallback_warning": (
            f"当前执行引擎替换了 {len(setting_fallbacks)} 个不适用设置，"
            "已使用该引擎默认值继续回测。"
            if setting_fallbacks
            else None
        ),
        "engine_result": {
            "engine": engine_result.get("engine"),
            "event_count": engine_result.get("event_count"),
            "signal_kind": execution.get("signal_kind"),
            "comparison": {
                "schema_version": 1,
                "engine": engine_result.get("engine"),
                "event_count": engine_result.get("event_count"),
                "signal_kind": execution.get("signal_kind"),
                "strategies": comparison_strategies,
            },
        },
    }
