"""Wire-level declarations for user-requestable Job outputs."""

from __future__ import annotations

from typing import Any, Iterable


OUTPUT_DEFINITIONS: dict[str, dict[str, Any]] = {
    "equity_curve": {
        "label": "净值曲线与回撤", "formats": ["svg", "json"],
        "presentation": "chart", "viewer": "equity_curve",
        "artifacts": ["equity_curve_report", "equity_curve_data", "equity_curve_receipt", "equity_curve_data_receipt"],
        "before_run": True, "after_run": True, "requires": ["result"],
        "analyses": ["backtest"],
    },
    "returns_over_time": {
        "label": "收益率随时间变化", "formats": ["svg", "json"],
        "presentation": "chart", "viewer": "line_chart",
        "artifacts": ["returns_over_time_report", "returns_over_time_data", "returns_over_time_report_receipt", "returns_over_time_data_receipt"],
        "before_run": True, "after_run": True, "requires": ["result"],
        "analyses": ["backtest"],
    },
    "metrics_over_time": {
        "label": "指标随时间变化", "formats": ["svg", "json"],
        "presentation": "chart", "viewer": "metrics_chart",
        "artifacts": ["metrics_over_time_report", "metrics_over_time_data", "metrics_over_time_report_receipt", "metrics_over_time_data_receipt"],
        "before_run": True, "after_run": True,
        "requires": ["result", "group_execution"], "analyses": ["backtest"],
    },
    "fee_detail": {
        "label": "手续费明细", "formats": ["csv", "json"],
        "presentation": "table", "viewer": "data_table",
        "artifacts": ["fee_detail_csv", "fee_detail_data", "fee_detail_csv_receipt", "fee_detail_data_receipt"],
        "before_run": True, "after_run": True, "requires": ["order_audit"],
        "analyses": ["backtest"],
    },
    "margin_detail": {
        "label": "保证金明细", "formats": ["csv", "json"],
        "presentation": "table", "viewer": "data_table",
        "artifacts": ["margin_detail_csv", "margin_detail_data", "margin_detail_csv_receipt", "margin_detail_data_receipt"],
        "before_run": True, "after_run": True,
        "requires": ["result", "group_execution"], "analyses": ["backtest"],
    },
    "ratio_detail": {
        "label": "收益、手续费、保证金占比", "formats": ["csv", "json"],
        "presentation": "table", "viewer": "data_table",
        "artifacts": ["ratio_detail_csv", "ratio_detail_data", "ratio_detail_csv_receipt", "ratio_detail_data_receipt"],
        "before_run": True, "after_run": True,
        "requires": ["result", "group_execution", "order_audit"],
        "analyses": ["backtest"],
    },
    "ic_series": {
        "label": "IC 序列", "formats": ["svg", "json"],
        "presentation": "chart", "viewer": "line_chart",
        "artifacts": [
            "ic_series_report", "ic_series_data",
            "ic_series_report_receipt", "ic_series_data_receipt",
        ],
        "before_run": True, "after_run": True, "requires": ["result"],
        "analyses": ["ic"],
        "default": True,
    },
    "ic_statistics": {
        "label": "IC 统计表", "formats": ["csv", "json"],
        "presentation": "table", "viewer": "data_table",
        "artifacts": [
            "ic_statistics_csv", "ic_statistics_data",
            "ic_statistics_csv_receipt", "ic_statistics_data_receipt",
        ],
        "before_run": True, "after_run": True, "requires": ["result"],
        "analyses": ["ic"],
        "default": True,
    },
}

_ALIASES = {
    "equity": "equity_curve", "equity_curve_report": "equity_curve",
    "returns": "returns_over_time", "return_series": "returns_over_time",
    "metrics": "metrics_over_time", "fees": "fee_detail",
    "fees_detail": "fee_detail", "margin": "margin_detail",
    "ratios": "ratio_detail",
}

_ARTIFACT_DESCRIPTIONS = {
    "result": "回测结果摘要（运行完成后由服务器保留）",
    "group_execution": "分组执行明细与组合曲线的原始数据",
    "order_audit": "订单、成交和结算手续费审计明细",
    "net_returns": "按时间记录的净收益序列",
    "equity_curve_report": "净值曲线图（SVG）",
    "equity_curve_data": "净值曲线与回撤数据（JSON）",
    "equity_curve_receipt": "净值曲线生成说明（JSON）",
    "equity_curve_data_receipt": "净值数据生成说明（JSON）",
    "returns_over_time_report": "收益率随时间变化图（SVG）",
    "returns_over_time_data": "收益率随时间变化数据（JSON）",
    "returns_over_time_report_receipt": "收益率图生成说明（JSON）",
    "returns_over_time_data_receipt": "收益率数据生成说明（JSON）",
    "metrics_over_time_report": "指标随时间变化图（SVG）",
    "metrics_over_time_data": "指标随时间变化数据（JSON）",
    "metrics_over_time_report_receipt": "指标图生成说明（JSON）",
    "metrics_over_time_data_receipt": "指标数据生成说明（JSON）",
    "fee_detail_csv": "手续费明细表（CSV）", "fee_detail_data": "手续费明细数据（JSON）",
    "fee_detail_csv_receipt": "手续费表生成说明（JSON）", "fee_detail_data_receipt": "手续费数据生成说明（JSON）",
    "margin_detail_csv": "保证金与名义金额明细表（CSV）", "margin_detail_data": "保证金明细数据（JSON）",
    "margin_detail_csv_receipt": "保证金表生成说明（JSON）", "margin_detail_data_receipt": "保证金数据生成说明（JSON）",
    "ratio_detail_csv": "收益、手续费和保证金占比表（CSV）", "ratio_detail_data": "收益、手续费和保证金占比数据（JSON）",
    "ratio_detail_csv_receipt": "占比表生成说明（JSON）", "ratio_detail_data_receipt": "占比数据生成说明（JSON）",
    "ic_series_report": "IC 序列图（SVG）", "ic_series_data": "IC 序列数据（JSON）",
    "ic_series_report_receipt": "IC 序列图生成说明（JSON）", "ic_series_data_receipt": "IC 序列数据生成说明（JSON）",
    "ic_statistics_csv": "IC 统计表（CSV）", "ic_statistics_data": "IC 统计数据（JSON）",
    "ic_statistics_csv_receipt": "IC 统计表生成说明（JSON）", "ic_statistics_data_receipt": "IC 统计数据生成说明（JSON）",
}


def output_capabilities() -> list[dict[str, Any]]:
    return [{"name": name, **dict(value)} for name, value in OUTPUT_DEFINITIONS.items()]


def output_declarations(requests: Iterable[str]) -> list[dict[str, Any]]:
    """Return the viewer contract stored with a Job detail response."""
    return [
        {
            "name": name,
            "label": OUTPUT_DEFINITIONS[name]["label"],
            "presentation": OUTPUT_DEFINITIONS[name]["presentation"],
            "viewer": OUTPUT_DEFINITIONS[name]["viewer"],
            "formats": list(OUTPUT_DEFINITIONS[name]["formats"]),
        }
        for name in normalize_output_requests(list(requests))
    ]


def artifact_description(name: str) -> str:
    return _ARTIFACT_DESCRIPTIONS.get(str(name), "Job 生成物")


def normalize_output_requests(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, list):
        raise ValueError("output_requests must be an array of names")
    normalized: list[str] = []
    for item in value:
        raw = item.get("name") if isinstance(item, dict) else item
        name = _ALIASES.get(str(raw or "").strip(), str(raw or "").strip())
        if name not in OUTPUT_DEFINITIONS:
            raise ValueError(f"unsupported output request {raw!r}; available: {', '.join(OUTPUT_DEFINITIONS)}")
        if name not in normalized:
            normalized.append(name)
    return normalized


def validate_output_requests(value: Any, analyses: Iterable[str]) -> list[str]:
    """Normalize requests and require a compatible selected analysis."""
    normalized = normalize_output_requests(value)
    selected = {str(item).strip() for item in analyses}
    for name in normalized:
        supported = {
            str(item).strip()
            for item in OUTPUT_DEFINITIONS[name].get("analyses") or ()
        }
        if supported and selected.isdisjoint(supported):
            raise ValueError(
                f"output request {name!r} requires one of analyses: "
                + ", ".join(sorted(supported))
            )
    return normalized


def default_output_requests(analyses: Iterable[str]) -> list[str]:
    selected = {str(item).strip() for item in analyses}
    return [
        name
        for name, definition in OUTPUT_DEFINITIONS.items()
        if definition.get("default")
        and not selected.isdisjoint(definition.get("analyses") or ())
    ]


def output_requests_for_analysis(
    requests: Iterable[str], analysis: str,
) -> list[str]:
    return [
        name
        for name in normalize_output_requests(list(requests))
        if analysis in (OUTPUT_DEFINITIONS[name].get("analyses") or ())
    ]


def source_artifacts_for(requests: Iterable[str]) -> set[str]:
    return {
        str(source)
        for name in requests
        for source in OUTPUT_DEFINITIONS.get(str(name), {}).get("requires") or ()
    }
