"""Dependency-free IC result projection contract.

The report-output layer imports this module while the tester settings package
may still be composing its application registry.  Keep this source contract
free of settings imports; the IC registration slice turns it into typed
``ResultProjectionDefinition`` objects for the public manifest.
"""

from __future__ import annotations

from typing import Any

_IC_RESULT_PROJECTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "summary", "label": "IC 汇总", "module": "ic_summary",
        "order": 10, "group": "overview", "viewer": "data_table",
        "source_artifacts": (
            "ic_statistics_summary_data", "ic_statistics_data",
        ),
        "output_requests": ("ic_statistics",), "presentation": "table",
        "default": True, "content_key": "summary",
        "empty_state": "暂无 IC 统计摘要",
    },
    {
        "key": "series", "label": "IC 序列", "module": "ic_delay",
        "order": 20, "group": "core_ic", "viewer": "line_chart",
        "source_artifacts": ("ic_series_data",),
        "output_requests": ("ic_series",), "presentation": "chart",
        "default": True, "content_key": "series",
        "empty_state": "暂无 IC 序列",
    },
    {
        "key": "decay", "label": "IC 衰减", "module": "ic_delay",
        "order": 30, "group": "decay_forward", "viewer": "line_chart",
        "source_artifacts": (
            "ic_statistics_data", "ic_holding_half_life_data",
        ),
        "output_requests": ("ic_statistics", "ic_holding_half_life"),
        "presentation": "chart",
        "content_key": "decay", "empty_state": "暂无多周期 IC 衰减数据",
    },
    {
        "key": "autocorrelation", "label": "自相关", "module": "ic_summary",
        "order": 40, "group": "time_series", "viewer": "line_chart",
        "source_artifacts": ("ic_autocorrelation_data",),
        "output_requests": ("ic_autocorrelation", "ic_statistics"),
        "presentation": "chart",
        "content_key": "autocorrelation",
        "empty_state": "IC 序列不足，无法估计自相关",
    },
    {
        "key": "rolling", "label": "Rolling IC", "module": "ic_summary",
        "order": 50, "group": "rolling_stability", "viewer": "data_table",
        "source_artifacts": ("ic_rolling_stability_data",),
        "output_requests": ("ic_rolling_stability", "ic_statistics"),
        "presentation": "table", "content_key": "rolling",
        "empty_state": "暂无滚动 IC 稳定性数据",
    },
    {
        "key": "periods", "label": "分期诊断", "module": "ic_summary",
        "order": 60, "group": "period_resampling", "viewer": "data_table",
        "source_artifacts": ("ic_period_diagnostics_data",),
        "output_requests": ("ic_period_diagnostics", "ic_statistics"),
        "presentation": "table", "content_key": "periods",
        "empty_state": "暂无分期诊断数据",
    },
    {
        "key": "resample", "label": "重采样诊断", "module": "ic_delay",
        "order": 70, "group": "period_resampling", "viewer": "data_table",
        "source_artifacts": ("ic_resample_stability_data",),
        "output_requests": ("ic_resample_stability", "ic_statistics"),
        "presentation": "table", "content_key": "resample",
        "empty_state": "暂无重采样稳定性数据",
    },
    {
        "key": "quantile_portfolio", "label": "分组组合统计",
        "module": "quantile_portfolio_statistics", "order": 90,
        "group": "quantile_portfolio", "viewer": "data_table",
        "source_artifacts": ("ic_quantile_portfolio_statistics_data",),
        "output_requests": ("ic_quantile_portfolio_statistics", "ic_statistics"),
        "presentation": "table", "content_key": "quantile_portfolio",
        "empty_state": "暂无分组组合统计数据",
    },
    {
        "key": "distribution", "label": "IC 分布", "module": "ic_summary",
        "order": 100, "group": "time_series", "viewer": "line_chart",
        "source_artifacts": ("ic_series_data",),
        "output_requests": ("ic_series",), "presentation": "chart",
        "content_key": "distribution", "empty_state": "暂无 IC 分布数据",
    },
)


def ic_result_projection_contracts() -> tuple[dict[str, Any], ...]:
    """Return immutable-shaped copies for manifest/declaration consumers."""

    return tuple(
        {
            **item,
            "source_artifacts": tuple(item["source_artifacts"]),
            "output_requests": tuple(item["output_requests"]),
        }
        for item in _IC_RESULT_PROJECTIONS
    )


__all__ = ["ic_result_projection_contracts"]
