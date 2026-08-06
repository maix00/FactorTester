"""Report rows for server-produced rolling IC stability summaries."""

from __future__ import annotations

from typing import Any


ROLLING_STABILITY_COLUMNS = [
    "factor_alias", "factor_ref", "ic_method", "forward_return_horizon",
    "entry_delay_bars", "window_key", "window_label", "window_kind",
    "rolling_window_unit", "requested_signal_count", "resolved_k_signals",
    "signal_interval_seconds", "signal_interval_source", "resolution_status",
    "resolution_reason", "n_signal_observations_available",
    "expected_sign", "expected_sign_source",
    "rolling_windows_count", "rolling_estimable",
    "rolling_mean_ic_p10", "rolling_mean_ic_p50", "rolling_mean_ic_p90",
    "rolling_icir_p10", "rolling_icir_p50", "rolling_icir_p90",
    "rolling_direction_rate_p10", "rolling_direction_rate_p50",
    "rolling_direction_rate_p90", "rolling_t_stat_hac_p10",
    "rolling_t_stat_hac_p50", "rolling_t_stat_hac_p90",
    "rolling_effective_n_ratio_p10", "rolling_effective_n_ratio_p50",
    "rolling_effective_n_ratio_p90", "rolling_mean_sign_consistency_rate",
    "rolling_direction_consistency_rate", "rolling_direction_failure_run_max",
    "rolling_hac_estimable_rate",
    "rolling_hac_ci_excludes_zero_expected_direction_rate",
    "expected_endpoint_span_seconds", "expected_coverage_span_seconds",
    "rolling_actual_endpoint_span_seconds_median",
    "rolling_actual_over_expected_span_median",
]


def rolling_stability_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten factor/horizon/delay/window summaries into report rows.

    Dense endpoint series stay in the Job result contract.  This artifact only
    carries one row per factor instance, horizon, delay, and rolling window.
    """

    rows: list[dict[str, Any]] = []
    for factor in result.get("factors") or ():
        if not isinstance(factor, dict):
            continue
        summaries = factor.get("rolling_ic_stability")
        if not isinstance(summaries, list):
            rolling = factor.get("rolling_ic")
            summaries = rolling.get("stability_summary") if isinstance(rolling, dict) else None
        if not isinstance(summaries, list):
            continue
        for summary in summaries:
            if not isinstance(summary, dict):
                continue
            rows.append({
                "factor_alias": str(factor.get("factor_alias") or factor.get("alias") or ""),
                "factor_ref": str(factor.get("factor_ref") or ""),
                "ic_method": str(factor.get("ic_method") or "rank"),
                "forward_return_horizon": str(summary.get("forward_return_horizon") or ""),
                "entry_delay_bars": int(summary.get("entry_delay_bars") or 0),
                **{
                    key: value for key, value in summary.items()
                    if key not in {"factor_alias", "forward_return_horizon", "entry_delay_bars"}
                },
            })
    return rows


def rolling_stability_semantics() -> dict[str, str]:
    return {
        "factor_alias": "完整参数化因子实例；由 factor_ref 绑定具体版本。",
        "forward_return_horizon": "未来收益标签 horizon，不是 rolling window。",
        "entry_delay_bars": "进入收益标签前的信号步延迟。",
        "rolling_window_unit": "固定为 signal_count；窗口长度只由有效信号观测数选择。",
        "requested_signal_count": "请求的有效信号观测数 K；不是因子参数，也不是时钟时长。",
        "rolling_mean_ic_p10": "滚动均值 IC 的下尾。",
        "rolling_mean_ic_p50": "滚动均值 IC 的中位数。",
        "rolling_mean_ic_p90": "滚动均值 IC 的上尾。",
        "rolling_icir_p50": "滚动 ICIR 的中位数。",
        "rolling_mean_sign_consistency_rate": "符合 expected_sign 的滚动均值窗口占比。",
        "rolling_direction_consistency_rate": "direction_rate >= 0.5 的窗口占比。",
        "rolling_direction_failure_run_max": "direction_rate < 0.5 的最长连续窗口数。",
        "rolling_hac_estimable_rate": "HAC 可估计窗口占比。",
        "rolling_hac_ci_excludes_zero_expected_direction_rate": "HAC 区间按 expected_sign 定向后排除零的窗口占比。",
        "rolling_actual_over_expected_span_median": "真实端点跨度与预期端点跨度的中位比值。",
        "expected_sign": "因子预期方向；滚动均值方向一致性按此方向判断。",
        "expected_sign_source": "预期方向的审计来源。",
    }


def rolling_stability_payload_extra(*, job_id: str | None = None) -> dict[str, Any]:
    return {
        "artifact_role": "report_table",
        "source_artifacts": ["result"],
        "rolling_ic_schema": "ic-rolling-v3",
        "column_semantics": rolling_stability_semantics(),
        "aggregation": {
            "row_key": [
                "factor_ref", "factor_alias", "ic_method",
                "forward_return_horizon", "entry_delay_bars", "window_key",
            ],
            "rolling_windows_are_dependent": True,
            "inference_note": "窗口间重叠，不把滚动行当作 IID 观测。",
            "window_selector": "signal_count",
        },
        "link_columns": ["factor_alias"],
        "job_id": str(job_id or ""),
    }
