"""Rolling IC diagnostics, response projections, and stability summaries.

The numerical point diagnostics remain owned by ``summarize_ic_series``.  This
module owns the rolling result contract: conversion from a resolved window to
endpoint rows, cross-window summaries, and the response shape used by report
builders. Request normalization lives in ``ic_rolling_params``; every rolling
window is selected by signal count.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

from tools.factors.tester_calc.single_factor_test.ic_diagnostics import (
    expected_sign_for_factor,
    ic_metric_selected,
    summarize_ic_series,
)
from server.modules.single_factor_test.ic_diagnostics import (
    json_safe_diagnostic_value,
    temporal_support_from_dict,
)
from server.modules.single_factor_test.ic_rolling_params import (
    ROLLING_IC_SCHEMA,
    RollingWindowSpec,
    normalize_rolling_window_specs,
    resolve_window_spec,
    signal_interval_seconds,
)


# Re-export the request types for old internal imports.  The implementation
# lives in ``ic_rolling_params``; this module owns only numerical diagnostics.
_signal_interval_seconds = signal_interval_seconds


def _finite_metric_values(rows: Iterable[dict[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        try:
            value = float(row.get(field))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    return values


def _quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p10": None, "p50": None, "p90": None}
    array = np.asarray(values, dtype=float)
    return {
        "p10": float(np.quantile(array, 0.10)),
        "p50": float(np.quantile(array, 0.50)),
        "p90": float(np.quantile(array, 0.90)),
    }


def _failure_run(values: Iterable[float], threshold: float = 0.5) -> int:
    longest = current = 0
    for value in values:
        if value < threshold:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _ci_excludes_zero(row: dict[str, Any], expected_sign: int | None) -> bool:
    lower = row.get("ci95_hac_lower")
    upper = row.get("ci95_hac_upper")
    try:
        lower_value = float(lower)
        upper_value = float(upper)
    except (TypeError, ValueError):
        return False
    sign = expected_sign if expected_sign in (-1, 1) else 1
    return sign * lower_value > 0 or sign * upper_value < 0


def _signal_timestamps(index: pd.Index) -> pd.DatetimeIndex:
    if isinstance(index, pd.MultiIndex):
        name = next(
            (item for item in index.names if item and str(item).startswith("_SIGNAL")),
            None,
        )
        level = index.names.index(name) if name is not None else -1
        return pd.DatetimeIndex(index.get_level_values(level))
    return pd.DatetimeIndex(index)


def rolling_stability_summary(
    rows: list[dict[str, Any]],
    *,
    expected_sign: int | None,
    resolution: dict[str, Any],
) -> dict[str, Any]:
    """Summarize dependent rolling rows without treating them as IID."""

    summary: dict[str, Any] = {
        **resolution,
        "window_key": resolution.get("key"),
        "window_label": resolution.get("label"),
        "window_kind": resolution.get("mode"),
        "expected_sign": expected_sign,
        "expected_sign_source": (
            "factor_alias:$Rev" if expected_sign == -1 else "factor_alias:raw"
            if expected_sign == 1 else None
        ),
        "rolling_windows_count": len(rows),
        "rolling_estimable": bool(rows),
        "rolling_mean_ic_p10": None,
        "rolling_mean_ic_p50": None,
        "rolling_mean_ic_p90": None,
        "rolling_icir_p10": None,
        "rolling_icir_p50": None,
        "rolling_icir_p90": None,
        "rolling_direction_rate_p10": None,
        "rolling_direction_rate_p50": None,
        "rolling_direction_rate_p90": None,
        "rolling_t_stat_hac_p10": None,
        "rolling_t_stat_hac_p50": None,
        "rolling_t_stat_hac_p90": None,
        "rolling_effective_n_ratio_p10": None,
        "rolling_effective_n_ratio_p50": None,
        "rolling_effective_n_ratio_p90": None,
        "rolling_mean_sign_consistency_rate": None,
        "rolling_direction_consistency_rate": None,
        "rolling_direction_failure_run_max": None,
        "rolling_hac_estimable_rate": None,
        "rolling_hac_ci_excludes_zero_expected_direction_rate": None,
        "rolling_actual_endpoint_span_seconds_median": None,
        "rolling_actual_over_expected_span_median": None,
    }
    if not rows:
        return summary

    for field, prefix in (
        ("mean_ic", "rolling_mean_ic"),
        ("icir_signal", "rolling_icir"),
        ("direction_rate", "rolling_direction_rate"),
        ("t_stat_hac", "rolling_t_stat_hac"),
        ("effective_n_capped_ratio", "rolling_effective_n_ratio"),
    ):
        quantiles = _quantiles(_finite_metric_values(rows, field))
        for suffix, value in quantiles.items():
            summary[f"{prefix}_{suffix}"] = value

    sign_consistent = []
    direction_consistent = []
    hac_estimable = []
    ci_excludes_zero = []
    for row in rows:
        try:
            mean_value = float(row.get("mean_ic"))
        except (TypeError, ValueError):
            mean_value = 0.0
        sign = expected_sign if expected_sign in (-1, 1) else 1
        sign_consistent.append(sign * mean_value > 0)
        try:
            direction_consistent.append(float(row.get("direction_rate")) >= 0.5)
        except (TypeError, ValueError):
            direction_consistent.append(False)
        hac_estimable.append(row.get("hac_status") == "estimable")
        ci_excludes_zero.append(_ci_excludes_zero(row, expected_sign))

    directions = [
        float(row["direction_rate"])
        for row in rows
        if row.get("direction_rate") is not None
    ]
    actual_spans = _finite_metric_values(rows, "actual_endpoint_span_seconds")
    expected_spans = _finite_metric_values(rows, "expected_endpoint_span_seconds")
    ratios = _finite_metric_values(rows, "actual_over_expected_span_ratio")
    summary.update({
        "rolling_mean_sign_consistency_rate": sum(sign_consistent) / len(rows),
        "rolling_direction_consistency_rate": sum(direction_consistent) / len(rows),
        "rolling_direction_failure_run_max": _failure_run(directions),
        "rolling_hac_estimable_rate": sum(hac_estimable) / len(rows),
        "rolling_hac_ci_excludes_zero_expected_direction_rate": sum(ci_excludes_zero) / len(rows),
        "rolling_actual_endpoint_span_seconds_median": (
            float(np.median(actual_spans)) if actual_spans else None
        ),
        "rolling_actual_over_expected_span_median": (
            float(np.median(ratios)) if ratios else None
        ),
    })
    if expected_spans:
        summary["expected_endpoint_span_seconds"] = expected_spans[0]
    return summary


def _rolling_rows(
    series: pd.Series,
    *,
    expected_sign: int | None,
    expected_sign_source: str | None,
    support_payload: dict[str, Any] | None,
    resolution: dict[str, Any],
    metric_selection: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    values = pd.Series(series).replace([np.inf, -np.inf], np.nan).dropna()
    count = resolution.get("resolved_k_signals")
    if count is None or len(values) < int(count):
        return [], []
    timestamps = _signal_timestamps(values.index)
    support = temporal_support_from_dict(support_payload)
    projected_rows: list[dict[str, Any]] = []
    full_rows: list[dict[str, Any]] = []
    for end_index in range(int(count) - 1, len(values)):
        start_index = end_index - int(count) + 1
        window_values = values.iloc[start_index:end_index + 1]
        stats = summarize_ic_series(
            window_values,
            expected_sign=expected_sign,
            expected_sign_source=expected_sign_source,
            temporal_support=support,
        )
        start_ts = pd.Timestamp(timestamps[start_index])
        end_ts = pd.Timestamp(timestamps[end_index])
        actual_span = float((end_ts - start_ts).total_seconds())
        row: dict[str, Any] = {
            "window_index": len(full_rows),
            "window_key": resolution["key"],
            "window_label": resolution["label"],
            "window_kind": resolution["mode"],
            "rolling_window_unit": "signal_count",
            "requested_signal_count": int(resolution["value"]),
            "resolved_k_signals": int(count),
            "window_start": start_ts.isoformat(),
            "window_end": end_ts.isoformat(),
            "actual_endpoint_span_seconds": actual_span,
            "expected_endpoint_span_seconds": resolution.get("expected_endpoint_span_seconds"),
            "expected_coverage_span_seconds": resolution.get("expected_coverage_span_seconds"),
            "actual_over_expected_span_ratio": (
                actual_span / float(resolution["expected_endpoint_span_seconds"])
                if resolution.get("expected_endpoint_span_seconds") not in (None, 0)
                else None
            ),
        }
        canonical = {
            key: json_safe_diagnostic_value(value)
            for key, value in stats.items()
            if key not in {"acf_vals", "temporal_support", "temporal_support_status"}
        }
        full_row = {**row, **canonical}
        full_rows.append(full_row)
        for field, value in stats.items():
            if field in {"acf_vals", "temporal_support", "temporal_support_status"}:
                continue
            if ic_metric_selected(metric_selection, field):
                row[field] = json_safe_diagnostic_value(value)
        # Compatibility aliases are present only when their canonical metric
        # was selected; this avoids the former selective-projection KeyError.
        if "mean_ic" in row:
            row["mean"] = row["mean_ic"]
        if "icir_signal" in row:
            row["ir"] = row["icir_signal"]
        projected_rows.append(row)
    return projected_rows, full_rows


def _empty_window_payload(
    resolution: dict[str, Any],
    *,
    expected_sign: int | None,
) -> dict[str, Any]:
    return {
        **resolution,
        "schema": ROLLING_IC_SCHEMA,
        "rolling_windows_count": 0,
        "rolling_estimable": False,
        "rows": [],
        "summary": rolling_stability_summary(
            [], expected_sign=expected_sign, resolution=resolution,
        ),
    }


def build_rolling_window_payload(
    series: pd.Series,
    *,
    expected_sign: int | None,
    expected_sign_source: str | None,
    support_payload: dict[str, Any] | None,
    fallback_signal_interval_seconds: float | None,
    spec: RollingWindowSpec,
    metric_selection: dict[str, Any] | None,
) -> dict[str, Any]:
    interval, interval_source = _signal_interval_seconds(
        support_payload, fallback_signal_interval_seconds,
    )
    resolution = resolve_window_spec(
        spec,
        signal_interval_seconds=interval,
        signal_interval_source=interval_source,
    )
    resolution["n_signal_observations_available"] = int(
        pd.Series(series).replace([np.inf, -np.inf], np.nan).dropna().shape[0]
    )
    if resolution["resolution_status"] != "estimable":
        return _empty_window_payload(resolution, expected_sign=expected_sign)
    rows, full_rows = _rolling_rows(
        series,
        expected_sign=expected_sign,
        expected_sign_source=expected_sign_source,
        support_payload=support_payload,
        resolution=resolution,
        metric_selection=metric_selection,
    )
    summary = rolling_stability_summary(
        full_rows,
        expected_sign=expected_sign,
        resolution=resolution,
    )
    arrays: dict[str, list[Any]] = {}
    array_fields = (
        "mean_ic", "median_ic", "std_ic", "mad_ic", "icir_signal",
        "t_stat_iid", "t_stat_hac", "se_hac", "ci95_hac_lower",
        "ci95_hac_upper", "hac_lag", "hac_status", "effective_n_raw",
        "effective_n_capped", "effective_n_ratio", "effective_n_capped_ratio",
        "direction_rate", "positive_ic_rate", "negative_ic_rate", "zero_ic_rate",
        "p10_ic", "p25_ic", "p50_ic", "p75_ic", "p90_ic", "skew_ic",
        "excess_kurtosis_ic", "ic_series_acf1", "ic_series_acf_half_life_signals",
    )
    for field in array_fields:
        values = [row.get(field) for row in full_rows]
        if any(value is not None for value in values):
            arrays[field] = values
    timestamps = [row["window_end"] for row in full_rows]
    actual_spans = [row["actual_endpoint_span_seconds"] for row in full_rows]
    expected_endpoints = [row["expected_endpoint_span_seconds"] for row in full_rows]
    expected_coverage = [row["expected_coverage_span_seconds"] for row in full_rows]
    legacy = {
        "window": resolution.get("resolved_k_signals"),
        "window_key": resolution.get("key"),
        "window_label": resolution.get("label"),
        "window_kind": resolution.get("mode"),
        "rolling_k_signals": [resolution.get("resolved_k_signals")] * len(rows),
        "span_definition": "endpoint_elapsed",
        "signal_interval_seconds": resolution.get("signal_interval_seconds"),
        "actual_endpoint_span_seconds": actual_spans,
        "expected_endpoint_span_seconds": expected_endpoints,
        "expected_coverage_span_seconds": expected_coverage,
        "dates": timestamps,
        **arrays,
        "mean": list(arrays.get("mean_ic", [])),
        "ir": list(arrays.get("icir_signal", [])),
    }
    return {
        **resolution,
        "schema": ROLLING_IC_SCHEMA,
        "rolling_windows_count": len(rows),
        "rolling_estimable": bool(rows),
        "rows": rows,
        "summary": summary,
        **legacy,
    }


def build_factor_rolling_ic(
    *,
    factor: Any,
    series_by_horizon_lag: dict[str, dict[int, pd.Series]],
    support_by_horizon_lag: dict[str, dict[int, dict[str, Any]]],
    primary_horizon: str | None,
    primary_lag: int,
    window_specs: list[RollingWindowSpec],
    metric_selection: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build all requested rolling windows for every horizon and delay."""

    if not window_specs:
        return None
    fallback_seconds = None
    try:
        fallback_seconds = float(factor.freq.value.total_seconds())
    except (AttributeError, TypeError, ValueError):
        pass
    expected_sign, expected_sign_source = _expected_sign(factor)
    by_horizon: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    summary_rows: list[dict[str, Any]] = []
    for horizon, by_lag in series_by_horizon_lag.items():
        horizon_payload: dict[str, dict[str, dict[str, Any]]] = {}
        for lag, series in by_lag.items():
            lag_payload: dict[str, dict[str, Any]] = {}
            support_payload = (support_by_horizon_lag.get(horizon) or {}).get(lag)
            for spec in window_specs:
                payload = build_rolling_window_payload(
                    series,
                    expected_sign=expected_sign,
                    expected_sign_source=expected_sign_source,
                    support_payload=support_payload,
                    fallback_signal_interval_seconds=fallback_seconds,
                    spec=spec,
                    metric_selection=metric_selection,
                )
                lag_payload[spec.key] = payload
                summary_rows.append({
                    "factor_alias": str(getattr(factor, "alias", "")),
                    "forward_return_horizon": str(horizon),
                    "entry_delay_bars": int(lag),
                    "expected_sign": expected_sign,
                    "expected_sign_source": expected_sign_source,
                    **payload["summary"],
                })
            horizon_payload[str(lag)] = lag_payload
        by_horizon[str(horizon)] = horizon_payload

    primary_horizon = str(primary_horizon or next(iter(by_horizon), ""))
    primary_lag_payload = by_horizon.get(primary_horizon, {}).get(str(primary_lag), {})
    first_primary = next(iter(primary_lag_payload.values()), None)
    result: dict[str, Any] = {
        "schema": ROLLING_IC_SCHEMA,
        "window_specs": [spec.to_dict() for spec in window_specs],
        "by_forward_horizon": by_horizon,
        "stability_summary": summary_rows,
    }
    if first_primary:
        # Keep the old primary object at the same path for existing clients.
        result["primary"] = first_primary
        result.update({
            key: value for key, value in first_primary.items()
            if key not in {"schema"}
        })
    return result


def _expected_sign(factor: Any) -> tuple[int, str]:
    return expected_sign_for_factor(factor)


def rolling_stability_semantics() -> list[dict[str, str]]:
    return [
        {"name": "rolling_mean_ic_p10", "meaning": "滚动均值 IC 的下尾，识别局部弱势窗口。"},
        {"name": "rolling_icir_p50", "meaning": "滚动 ICIR 中位数，描述典型窗口的一致性。"},
        {"name": "rolling_mean_sign_consistency_rate", "meaning": "符合 expected_sign 的滚动均值窗口占比。"},
        {"name": "rolling_direction_failure_run_max", "meaning": "方向率低于 50% 的最长连续滚动窗口数。"},
        {"name": "rolling_hac_estimable_rate", "meaning": "HAC 可估计滚动窗口占比，不等同于因子通过率。"},
        {"name": "rolling_hac_ci_excludes_zero_expected_direction_rate", "meaning": "HAC 区间在预期方向上排除零的窗口占比。"},
        {"name": "rolling_actual_over_expected_span_median", "meaning": "真实端点跨度与预期跨度的中位比值，用于审计交易休市和不规则间隔。"},
    ]
