"""Project grouped engine output into the stable research-result contract."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from tools.factors.tester_calc.single_factor_test.portfolio_metrics import (
    compute_return_metrics,
    infer_periods_per_year,
)

from .strategy_identity import strategy_configuration_id


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def _infer_periods_per_year(index_like: Any) -> float:
    return infer_periods_per_year(index_like)


def _compute_return_metrics(
    returns: np.ndarray,
    *,
    index_like: Any = None,
    avg_turnover: Any = None,
) -> dict[str, Any]:
    return compute_return_metrics(
        returns, index_like=index_like, avg_turnover=avg_turnover,
    )


def _event_notional_turnover(portfolio: dict[str, Any]) -> dict[str, Any]:
    """Compute turnover from retained per-event notional snapshots.

    This is intentionally separate from the vectorized target-weight proxy.
    The denominator is the event-time equity and the numerator is the absolute
    change in signed product notionals, so price drift is part of this event
    snapshot measure.  It is not claimed to be fill-only turnover.
    """
    notionals = portfolio.get("notional_curve") or {}
    equities = portfolio.get("equity_curve") or {}
    if not isinstance(notionals, dict) or not isinstance(equities, dict):
        return {"average": None, "observations": 0, "source": "unavailable"}
    timestamps = sorted(
        set(notionals) & set(equities),
        key=lambda value: pd.Timestamp(value),
    )
    if not timestamps:
        return {"average": None, "observations": 0, "source": "unavailable"}
    previous: dict[str, float] = {}
    observations: list[float] = []
    for timestamp in timestamps:
        try:
            equity = float(equities[timestamp])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(equity) or abs(equity) <= 1e-12:
            continue
        current: dict[str, float] = {}
        row = notionals.get(timestamp) or {}
        if isinstance(row, dict):
            for product, notional in row.items():
                try:
                    value = float(notional) / equity
                except (TypeError, ValueError):
                    continue
                if math.isfinite(value):
                    current[str(product)] = value
        keys = set(previous) | set(current)
        observations.append(sum(abs(current.get(key, 0.0) - previous.get(key, 0.0)) for key in keys))
        previous = current
    return {
        "average": float(sum(observations) / len(observations)) if observations else None,
        "observations": len(observations),
        "source": "event_notional_curve" if observations else "unavailable",
    }


def _portfolio_turnover(portfolio: dict[str, Any]) -> dict[str, Any]:
    """Prefer native fill audit; retain snapshot fallback for other engines."""
    fill = portfolio.get("fill_turnover")
    if isinstance(fill, dict) and fill.get("source") == "fill_audit":
        return {
            "average": fill.get("average"),
            "observations": int(fill.get("observations") or 0),
            "source": "fill_audit",
        }
    snapshot = _event_notional_turnover(portfolio)
    if snapshot.get("source") != "unavailable":
        return snapshot
    return {"average": None, "observations": 0, "source": "unavailable"}


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
        str(
            owner.get("display_name")
            or owner.get("group_name")
            or owner.get("strategy_id")
            or owner.get("group_id")
            or ""
        )
        for owner in execution["group_owner"]
    )

    for owner in execution["group_owner"]:
        strategy_id = str(
            owner.get("strategy_id") or owner.get("group_id") or ""
        )
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
        display_name = str(
            owner.get("display_name") or owner.get("group_name") or strategy_id
        )
        metrics_key = (
            display_name
            if display_name_counts[display_name] == 1
            else strategy_id
        )
        settings = settings_by_group[strategy_id]
        configuration_id = str(
            owner.get("strategy_configuration_id")
            or strategy_configuration_id(owner, settings)
        )
        strategy_target_trace = target_trace.get(strategy_id, {})
        execution_trace = portfolio.get("execution_trace") or {}
        turnover = _portfolio_turnover(portfolio)
        comparison_strategies.append({
            "strategy_id": strategy_id,
            "strategy_configuration_id": configuration_id,
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
            "turnover_observations": int(turnover["observations"]),
            "turnover_source": turnover["source"],
        })
        module_outputs: dict[str, Any] = {}
        if registry is not None:
            module_outputs = registry.collect_outputs(
                group_result=group_result,
                owner=owner,
                settings=settings,
            )
        groups.append({
            # Canonical result identity.  `group_id` remains only as the
            # transport selector required by existing group-detail routes;
            # `key` and `name` are not strategy fields and are intentionally
            # not emitted by this new writer.
            "strategy_id": strategy_id,
            "strategy_configuration_id": configuration_id,
            "display_name": display_name,
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
            "turnover_semantics": (
                "fill_notional_over_equity; actual filled quantity × fill price × "
                "multiplier, aggregated by fill timestamp"
                if turnover["source"] == "fill_audit"
                else "event_notional_weight_change; includes mark-to-market price drift; not fill-only"
            ),
            "turnover_observations": int(turnover["observations"]),
            "turnover_source": turnover["source"],
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
            avg_turnover=turnover["average"],
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
