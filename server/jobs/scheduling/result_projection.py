"""Bounded live/persisted result projections used by worker scheduling."""

from __future__ import annotations

from typing import Any

import orjson


def _json_bytes(value: Any) -> bytes:
    return orjson.dumps(value, option=orjson.OPT_SERIALIZE_NUMPY, default=str)


def _bounded_summary(data: dict[str, Any], *, max_bytes: int = 512 * 1024) -> dict[str, Any]:
    raw = _json_bytes(data)
    if len(raw) <= max_bytes:
        return dict(data)
    summary: dict[str, Any] = {
        "success": bool(data.get("success", True)),
        "summary_truncated": True,
        "full_result_bytes": len(raw),
    }
    groups = data.get("groups")
    group_reserve = min(128 * 1024, max_bytes // 2) if isinstance(groups, list) else 0
    non_group_limit = max_bytes - group_reserve
    for key, value in data.items():
        if key in {"success", "groups", "equity_curve", "curves", "details", "engine_result"}:
            continue
        candidate = {**summary, key: value}
        if len(_json_bytes(candidate)) <= non_group_limit:
            summary[key] = value
    if isinstance(groups, list):
        candidate = {**summary, "groups": groups}
        if len(_json_bytes(candidate)) <= max_bytes:
            summary["groups"] = groups
        else:
            chart_groups, downsampled = _bounded_chart_groups(
                groups, byte_budget=max_bytes - len(_json_bytes(summary)),
            )
            summary["groups"] = chart_groups
            summary["groups_chart_only"] = True
            summary["equity_curve_downsampled"] = downsampled
    return summary


def _compact_ic_stats(stats: dict[str, Any]) -> dict[str, Any]:
    """Keep named scalar IC diagnostics while dropping dense series payloads."""
    fields = (
        "diagnostics_schema", "n_signal_observations", "mean_ic", "median_ic",
        "std_ic", "std_ic_ddof", "se_iid", "ci95_iid_lower", "ci95_iid_upper",
        "mad_ic", "icir_signal", "t_stat_iid", "t_stat_hac",
        "se_hac", "ci95_hac_lower", "ci95_hac_upper", "hac_lag",
        "hac_lag_source", "hac_lag_formula", "hac_kernel", "hac_status",
        "hac_reason", "hac_overlap_support_seconds",
        "hac_overlap_support_components_seconds", "effective_n_raw",
        "effective_n_capped", "effective_n_ratio", "effective_n_capped_ratio",
        "ess_exceeds_n", "hac_lrv_to_iid_variance_ratio", "direction_rate", "positive_ic_rate",
        "negative_ic_rate", "zero_ic_rate", "ic_series_acf1",
        "ic_series_acf_half_life_signals", "ic_series_acf_half_life_status",
        "ic_series_ar1_rho", "ic_series_ar1_r_squared",
        "ic_series_ar1_half_life_status", "ic_series_ar1_half_life_signals",
        "ic_series_ar1_half_life_seconds", "ic_series_ar1_n_signal_pairs",
        "ic_series_ar1_method", "acf_estimator", "ess_definition",
        "t_stat_hac_reference", "p10_ic", "p25_ic", "p50_ic", "p75_ic",
        "p90_ic", "skew_ic", "excess_kurtosis_ic", "forward_ic_half_life",
        "forward_ic_half_life_exponential",
        # Deprecated aliases preserve old compact-summary readers.
        "mean", "std", "IR", "t_stat", "ac1", "half_life",
    )
    return {field: stats[field] for field in fields if field in stats}


def _compact_period_diagnostics(value: dict[str, Any]) -> dict[str, Any]:
    """Retain period-level statuses/counts, not every block's IC sequence."""
    periods = value.get("periods")
    if not isinstance(periods, dict):
        return {"schema": value.get("schema")}
    compact_periods = {}
    for label, item in periods.items():
        if not isinstance(item, dict):
            continue
        compact_periods[str(label)] = {
            key: item.get(key)
            for key in (
                "rule", "min_signal_observations", "min_periods",
                "n_periods_total", "n_periods_estimable",
                "n_periods_hac_estimable", "period_estimability_status",
            )
            if key in item
        }
    return {"schema": value.get("schema"), "periods": compact_periods}


def _compact_rolling_ic(value: dict[str, Any]) -> dict[str, Any]:
    """Keep rolling configuration and endpoints; dense arrays stay in artifacts."""
    return {
        key: value.get(key)
        for key in (
            "window", "rolling_k_signals", "span_definition",
            "signal_interval_seconds", "expected_endpoint_span_seconds",
            "expected_coverage_span_seconds",
        )
        if key in value
    }


def _compact_runtime_info_rows(
    value: Any,
    *,
    max_rows: int = 128,
    max_bytes: int = 24 * 1024,
) -> list[dict[str, Any]]:
    """Keep bounded diagnostic rows ahead of large chart/result fields."""
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value[:max_rows]:
        if not isinstance(item, dict):
            continue
        candidate = dict(item)
        if len(_json_bytes(rows + [candidate])) > max_bytes:
            break
        rows.append(candidate)
    return rows


def persisted_result_summary(
    data: dict[str, Any], *, max_bytes: int = 64 * 1024,
) -> dict[str, Any]:
    """Project terminal facts without persisting chart point sequences."""
    projected: dict[str, Any] = {
        "success": bool(data.get("success", True)),
        "equity_curve_points_persisted": False,
    }
    factors = data.get("factors")
    if isinstance(factors, list):
        compact_factors = []
        for factor in factors:
            if not isinstance(factor, dict):
                continue
            compact_stats: dict[str, dict[str, dict[str, Any]]] = {}
            for horizon, by_delay in (factor.get("ic_stats_by_forward_horizon") or {}).items():
                if not isinstance(by_delay, dict):
                    continue
                for delay, stats in by_delay.items():
                    if isinstance(stats, dict):
                        compact_stats.setdefault(str(horizon), {})[str(delay)] = _compact_ic_stats(stats)
            compact = {
                key: factor.get(key)
                for key in (
                    "factor_alias", "factor_ref", "alias", "primary_forward_return_horizon",
                    "forward_ic_half_life", "forward_ic_half_life_by_entry_delay",
                    "forward_ic_half_life_exponential",
                    "forward_ic_half_life_exponential_by_entry_delay",
                )
                if key in factor
            }
            if factor.get("ic_diagnostics_schema"):
                compact["ic_diagnostics_schema"] = factor["ic_diagnostics_schema"]
            if isinstance(factor.get("period_diagnostics"), dict):
                compact["period_diagnostics"] = _compact_period_diagnostics(factor["period_diagnostics"])
            if isinstance(factor.get("rolling_ic"), dict):
                compact["rolling_ic"] = _compact_rolling_ic(factor["rolling_ic"])
            if compact_stats:
                compact["ic_stats_by_forward_horizon"] = compact_stats
            compact_factors.append(compact)
        candidate = {**projected, "factors": compact_factors}
        if compact_factors and len(_json_bytes(candidate)) <= max_bytes:
            projected["factors"] = compact_factors
    if data.get("equity_curve_artifact_available") is True:
        projected.update({
            "equity_curve_artifact_available": True,
            "equity_curve_artifact": "equity_curve_report",
            "equity_curve_receipt_artifact": "equity_curve_receipt",
        })
    runtime_rows = _compact_runtime_info_rows(data.get("runtime_info_rows"))
    if runtime_rows:
        candidate = {**projected, "runtime_info_rows": runtime_rows}
        if len(_json_bytes(candidate)) <= max_bytes:
            projected["runtime_info_rows"] = runtime_rows
    excluded = {
        "groups", "equity_curve", "curves", "details", "engine_result",
        "factors", "runtime_info_rows",
    }
    for key, value in data.items():
        if key in excluded or key == "success":
            continue
        candidate = {**projected, key: value}
        if len(_json_bytes(candidate)) <= max_bytes:
            projected[key] = value

    groups = data.get("groups")
    if isinstance(groups, list):
        compact_groups = [_persisted_group(value) for value in groups]
        candidate = {**projected, "groups": compact_groups}
        if len(_json_bytes(candidate)) <= max_bytes:
            projected["groups"] = compact_groups
        else:
            projected["group_count"] = len(compact_groups)
            projected["group_summaries_omitted"] = True
    return projected


def _persisted_group(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    curve_keys = {
        "timestamps", "total_equity", "gross_returns", "net_returns",
        "equity_curve", "curves", "daily_returns", "period_returns",
        "pre_rebalance_total_equity", "post_rebalance_total_equity",
    }
    compact: dict[str, Any] = {}
    for key, item in value.items():
        if key in curve_keys:
            continue
        if len(_json_bytes(item)) <= 16 * 1024:
            compact[key] = item
    compact["equity_curve_points_persisted"] = False
    return compact


def _bounded_chart_groups(groups: list[Any], *, byte_budget: int) -> tuple[list[dict[str, Any]], bool]:
    """Keep the Web chart contract even when the full job result is truncated."""
    scalar_keys = (
        "key", "name", "group_id", "group_index", "product_path_selection_id",
        "factor_alias", "engine", "allocation_policy", "rebalance_trigger",
        "position_policy", "target_trace_available", "snapshot_available",
        "is_ls", "ls_info",
    )
    stride = 1
    while True:
        result = []
        for value in groups:
            group = value if isinstance(value, dict) else {}
            compact = {key: group[key] for key in scalar_keys if key in group}
            timestamps = list(group.get("timestamps") or [])
            equity = list(group.get("total_equity") or [])
            gross_returns = list(group.get("gross_returns") or [])
            point_count = min(len(timestamps), len(equity))
            indices = list(range(0, point_count, stride))
            if point_count and (not indices or indices[-1] != point_count - 1):
                indices.append(point_count - 1)
            compact["timestamps"] = [timestamps[index] for index in indices]
            compact["total_equity"] = [equity[index] for index in indices]
            if len(gross_returns) >= point_count:
                compact["gross_returns"] = [gross_returns[index] for index in indices]
            compact["equity_curve_original_points"] = point_count
            result.append(compact)
        if len(_json_bytes(result)) <= max(0, byte_budget) or stride >= 1024:
            return result, stride > 1
        stride *= 2
