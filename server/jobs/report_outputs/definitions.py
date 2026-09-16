"""Wire-level declarations for user-requestable Job outputs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .backtest_tables import BACKTEST_TABLE_DEFINITIONS, BACKTEST_TABLE_DESCRIPTIONS

OUTPUT_DEFINITIONS: dict[str, dict[str, Any]] = {
    "factor_series": {
        # The rendered series is a real report figure: list it as a rendition so
        # the job's special section can mount it (a JSON-only output left the
        # auto-mounted section with nothing to show).
        "label": "因子序列", "formats": ["svg", "json"],
        "presentation": "chart", "viewer": "factor_series",
        "artifacts": [
            "factor_series_data", "factor_series_receipt", "factor_series_chart",
            "factor_series_market_chart",
        ],
        "canonical_artifact": "factor_series_data",
        "rendition_artifacts": [
            "factor_series_chart", "factor_series_market_chart",
        ],
        "receipt_artifact": "factor_series_receipt",
        # IC/backtest only retain these values when the primary run requests
        # them; the report supplemental builder cannot recreate tester state.
        "before_run": True, "after_run": False, "requires": [],
        "analyses": ["factor_evaluation", "ic", "backtest"],
        "result_surface": "factor_series", "result_view": "factor_series",
        "result_order": 5,
    },
    "equity_curve": {
        "label": "净值曲线与回撤", "formats": ["svg", "json"],
        "presentation": "chart", "viewer": "equity_curve",
        "artifacts": ["equity_curve_report", "equity_curve_data", "equity_curve_receipt"],
        "canonical_artifact": "equity_curve_data",
        "rendition_artifacts": ["equity_curve_report"],
        "receipt_artifact": "equity_curve_receipt",
        "before_run": True, "after_run": True, "requires": ["result"],
        "analyses": ["backtest"],
        "result_surface": "time_series", "result_view": "equity",
        "supplemental_bundle": "time_series", "result_order": 10,
    },
    "returns_over_time": {
        "label": "收益率随时间变化", "formats": ["svg", "json"],
        "presentation": "chart", "viewer": "line_chart",
        "artifacts": ["returns_over_time_report", "returns_over_time_data", "returns_over_time_receipt"],
        "canonical_artifact": "returns_over_time_data",
        "rendition_artifacts": ["returns_over_time_report"],
        "receipt_artifact": "returns_over_time_receipt",
        "before_run": True, "after_run": True, "requires": ["result"],
        "analyses": ["backtest"],
        "result_surface": "time_series", "result_view": "returns",
        "supplemental_bundle": "time_series", "result_order": 20,
    },
    "metrics_over_time": {
        "label": "指标随时间变化", "formats": ["svg", "json"],
        "presentation": "chart", "viewer": "metrics_chart",
        "artifacts": ["metrics_over_time_report", "metrics_over_time_data", "metrics_over_time_receipt"],
        "canonical_artifact": "metrics_over_time_data",
        "rendition_artifacts": ["metrics_over_time_report"],
        "receipt_artifact": "metrics_over_time_receipt",
        "before_run": True, "after_run": True,
        "requires": ["result", "group_execution"], "analyses": ["backtest"],
        "result_retention_mode": "full",
        "result_surface": "time_series", "result_view": "metrics",
        "supplemental_bundle": "time_series", "result_order": 30,
    },
    "fee_detail": {
        "label": "手续费明细", "formats": ["csv", "json"],
        "presentation": "table", "viewer": "data_table",
        "artifacts": ["fee_detail_csv", "fee_detail_data", "fee_detail_receipt"],
        "canonical_artifact": "fee_detail_data",
        "rendition_artifacts": ["fee_detail_csv"],
        "receipt_artifact": "fee_detail_receipt",
        "before_run": True, "after_run": True, "requires": ["order_audit"],
        "analyses": ["backtest"],
        "result_surface": "execution_account", "result_view": "fees",
        "supplemental_bundle": "execution_account", "result_order": 60,
    },
    "margin_detail": {
        "label": "保证金明细", "formats": ["csv", "json"],
        "presentation": "table", "viewer": "data_table",
        "artifacts": ["margin_detail_csv", "margin_detail_data", "margin_detail_receipt"],
        "canonical_artifact": "margin_detail_data",
        "rendition_artifacts": ["margin_detail_csv"],
        "receipt_artifact": "margin_detail_receipt",
        "before_run": True, "after_run": True,
        "requires": ["result", "group_execution"], "analyses": ["backtest"],
        "result_retention_mode": "full",
        "result_surface": "execution_account", "result_view": "margin",
        "supplemental_bundle": "execution_account", "result_order": 50,
    },
    "ratio_detail": {
        "label": "收益、手续费、保证金占比", "formats": ["csv", "json"],
        "presentation": "table", "viewer": "data_table",
        "artifacts": ["ratio_detail_csv", "ratio_detail_data", "ratio_detail_receipt"],
        "canonical_artifact": "ratio_detail_data",
        "rendition_artifacts": ["ratio_detail_csv"],
        "receipt_artifact": "ratio_detail_receipt",
        "before_run": True, "after_run": True,
        "requires": ["result", "group_execution", "order_audit"],
        "analyses": ["backtest"],
        "result_retention_mode": "full",
        "result_surface": "return_analysis", "result_view": "cost_ratios",
        "supplemental_bundle": "return_risk", "result_order": 10,
    },
    "group_research_detail": {
        "label": "分组研究详情", "formats": ["json"],
        "presentation": "detail", "viewer": "group_research_detail",
        # The standard result UI reads a compact core artifact produced once
        # during post_replay.  It never requires the full execution trace.
        "artifacts": [],
        "before_run": True, "after_run": False,
        "requires": ["strategy_analysis_source"],
        "analyses": ["backtest"],
    },
    "ic_series": {
        "label": "IC 序列", "formats": ["svg", "json"],
        "presentation": "chart", "viewer": "line_chart",
        "artifacts": [
            "ic_series_report", "ic_series_data",
            "ic_series_receipt",
        ],
        "canonical_artifact": "ic_series_data",
        "rendition_artifacts": ["ic_series_report"],
        "receipt_artifact": "ic_series_receipt",
        "before_run": True, "after_run": True, "requires": ["result"],
        "analyses": ["ic"],
        "default": True,
    },
    "ic_statistics": {
        "label": "IC 统计表", "formats": ["csv", "json"],
        "presentation": "table", "viewer": "data_table",
        "artifacts": [
            "ic_statistics_csv", "ic_statistics_data",
            "ic_statistics_receipt",
            "ic_statistics_summary_csv", "ic_statistics_summary_data",
            "ic_statistics_summary_receipt",
            "ic_rolling_stability_csv", "ic_rolling_stability_data",
            "ic_rolling_stability_receipt",
            "ic_period_diagnostics_csv", "ic_period_diagnostics_data",
            "ic_period_diagnostics_receipt",
            "ic_quantile_portfolio_statistics_csv", "ic_quantile_portfolio_statistics_data",
            "ic_quantile_portfolio_statistics_receipt",
            "ic_resample_stability_csv", "ic_resample_stability_data",
            "ic_resample_stability_receipt",
            "ic_autocorrelation_csv", "ic_autocorrelation_data",
            "ic_autocorrelation_receipt",
        ],
        "canonical_artifact": "ic_statistics_data",
        "rendition_artifacts": ["ic_statistics_csv"],
        "receipt_artifact": "ic_statistics_receipt",
        "before_run": True, "after_run": True, "requires": ["result"],
        "analyses": ["ic"],
        "default": True,
    },
    "ic_statistics_summary": {
        "label": "IC 统计摘要表", "formats": ["csv", "json"],
        "presentation": "table", "viewer": "data_table",
        "artifacts": [
            "ic_statistics_summary_csv", "ic_statistics_summary_data",
            "ic_statistics_summary_receipt",
        ],
        "canonical_artifact": "ic_statistics_summary_data",
        "rendition_artifacts": ["ic_statistics_summary_csv"],
        "receipt_artifact": "ic_statistics_summary_receipt",
        "before_run": True, "after_run": True, "requires": ["result"],
        "analyses": ["ic"], "auto_when": "ic_statistics",
        # This category is emitted by the aggregate IC statistics builder;
        # artifact recovery should retain the historical aggregate owner.
        "artifact_owner": "ic_statistics",
    },
    "ic_rolling_stability": {
        "label": "滚动 IC 稳定性表", "formats": ["csv", "json"],
        "presentation": "table", "viewer": "data_table",
        "artifacts": [
            "ic_rolling_stability_csv", "ic_rolling_stability_data",
            "ic_rolling_stability_receipt",
        ],
        "canonical_artifact": "ic_rolling_stability_data",
        "rendition_artifacts": ["ic_rolling_stability_csv"],
        "receipt_artifact": "ic_rolling_stability_receipt",
        "before_run": True, "after_run": True, "requires": ["result"],
        "analyses": ["ic"],
        # IC statistics auto-emits this artifact when rolling summaries exist;
        # keep the standalone request opt-in so legacy default declarations
        # remain stable and empty tables are never created.
        "auto_when": "ic_statistics",
    },
    "ic_period_diagnostics": {
        "label": "IC 周期诊断表", "formats": ["csv", "json"],
        "presentation": "table", "viewer": "data_table",
        "artifacts": [
            "ic_period_diagnostics_csv", "ic_period_diagnostics_data",
            "ic_period_diagnostics_receipt",
        ],
        "canonical_artifact": "ic_period_diagnostics_data",
        "rendition_artifacts": ["ic_period_diagnostics_csv"],
        "receipt_artifact": "ic_period_diagnostics_receipt",
        "before_run": True, "after_run": True, "requires": ["result"],
        "analyses": ["ic"],
        "auto_when": "ic_statistics",
    },
    "ic_quantile_portfolio_statistics": {
        "label": "IC 分组组合统计表", "formats": ["csv", "json"],
        "presentation": "table", "viewer": "data_table",
        "artifacts": [
            "ic_quantile_portfolio_statistics_csv", "ic_quantile_portfolio_statistics_data",
            "ic_quantile_portfolio_statistics_receipt",
        ],
        "canonical_artifact": "ic_quantile_portfolio_statistics_data",
        "rendition_artifacts": ["ic_quantile_portfolio_statistics_csv"],
        "receipt_artifact": "ic_quantile_portfolio_statistics_receipt",
        "before_run": True, "after_run": True, "requires": ["result"],
        "analyses": ["ic"],
        "auto_when": "ic_statistics",
    },
    "ic_holding_half_life": {
        "label": "真实持有期 IC 半衰期图", "formats": ["svg", "json"],
        "presentation": "chart", "viewer": "line_chart",
        "artifacts": [
            "ic_holding_half_life_report", "ic_holding_half_life_data",
            "ic_holding_half_life_receipt",
        ],
        "canonical_artifact": "ic_holding_half_life_data",
        "rendition_artifacts": ["ic_holding_half_life_report"],
        "receipt_artifact": "ic_holding_half_life_receipt",
        "before_run": True, "after_run": True, "requires": ["result"],
        "analyses": ["ic"],
        # The IC result already contains the horizon-level means needed for
        # this O(H) diagnostic.  Keep it in the default IC report whitelist;
        # callers can still omit it by explicitly supplying output_requests.
        "default": True,
    },
    "ic_resample_stability": {
        "label": "IC 重采样稳定性表", "formats": ["csv", "json"],
        "presentation": "table", "viewer": "data_table",
        "artifacts": [
            "ic_resample_stability_csv", "ic_resample_stability_data",
            "ic_resample_stability_receipt",
        ],
        "canonical_artifact": "ic_resample_stability_data",
        "rendition_artifacts": ["ic_resample_stability_csv"],
        "receipt_artifact": "ic_resample_stability_receipt",
        "before_run": True, "after_run": True, "requires": ["result"],
        "analyses": ["ic"],
    },
    "ic_autocorrelation": {
        "label": "IC 自相关表", "formats": ["csv", "json"],
        "presentation": "table", "viewer": "data_table",
        "artifacts": [
            "ic_autocorrelation_csv", "ic_autocorrelation_data",
            "ic_autocorrelation_receipt",
        ],
        "canonical_artifact": "ic_autocorrelation_data",
        "rendition_artifacts": ["ic_autocorrelation_csv"],
        "receipt_artifact": "ic_autocorrelation_receipt",
        "before_run": True, "after_run": True, "requires": ["result"],
        "analyses": ["ic"],
    },
}

OUTPUT_DEFINITIONS.update(BACKTEST_TABLE_DEFINITIONS)

_ALIASES = {
    "equity": "equity_curve", "equity_curve_report": "equity_curve",
    "returns": "returns_over_time", "return_series": "returns_over_time",
    "metrics": "metrics_over_time", "fees": "fee_detail",
    "fees_detail": "fee_detail", "margin": "margin_detail",
    "ratios": "ratio_detail",
    "holding_half_life": "ic_holding_half_life",
}

_ARTIFACT_DESCRIPTIONS = {
    "factor_series_data": "各因子在涉及产品上的因子值序列（JSON）",
    "factor_series_receipt": "因子序列生成说明（JSON）",
    "factor_series_chart": "因子与各内嵌层序列图（SVG）",
    "result": "回测结果摘要（运行完成后由服务器保留）",
    "group_execution": "分组执行明细与组合曲线的原始数据",
    "strategy_analysis_source": "按需计算策略分析所需的基础数据",
    "order_audit": "订单、成交和结算手续费审计明细",
    "net_returns": "按时间记录的净收益序列",
    "equity_curve_report": "净值曲线图（SVG）",
    "equity_curve_data": "净值曲线与回撤数据（JSON）",
    "equity_curve_receipt": "净值曲线生成说明（JSON）",
    "returns_over_time_report": "收益率随时间变化图（SVG）",
    "returns_over_time_data": "收益率随时间变化数据（JSON）",
    "returns_over_time_receipt": "收益率结果生成说明（JSON）",
    "metrics_over_time_report": "指标随时间变化图（SVG）",
    "metrics_over_time_data": "指标随时间变化数据（JSON）",
    "metrics_over_time_receipt": "指标结果生成说明（JSON）",
    "fee_detail_csv": "手续费明细表（CSV）", "fee_detail_data": "手续费明细数据（JSON）",
    "fee_detail_receipt": "手续费明细生成说明（JSON）",
    "margin_detail_csv": "保证金与名义金额明细表（CSV）", "margin_detail_data": "保证金明细数据（JSON）",
    "margin_detail_receipt": "保证金明细生成说明（JSON）",
    "ratio_detail_csv": "收益、手续费和保证金占比表（CSV）", "ratio_detail_data": "收益、手续费和保证金占比数据（JSON）",
    "ratio_detail_receipt": "收益、手续费和保证金占比生成说明（JSON）",
    "ic_series_report": "IC 序列图（SVG）", "ic_series_data": "IC 序列数据（JSON）",
    "ic_series_receipt": "IC 序列生成说明（JSON）",
    "ic_statistics_csv": "IC 统计表（CSV）", "ic_statistics_data": "IC 统计数据（JSON）",
    "ic_statistics_receipt": "IC 统计生成说明（JSON）",
    "ic_statistics_summary_csv": "IC 统计摘要表（报告 artifact，CSV）",
    "ic_statistics_summary_data": "IC 统计摘要表（报告 artifact，JSON）",
    "ic_statistics_summary_receipt": "IC 统计摘要生成说明（JSON）",
    "ic_rolling_stability_csv": "滚动 IC 稳定性表（CSV）",
    "ic_rolling_stability_data": "滚动 IC 稳定性数据（JSON）",
    "ic_rolling_stability_receipt": "滚动 IC 稳定性生成说明（JSON）",
    "ic_period_diagnostics_csv": "IC 周期诊断表（CSV）",
    "ic_period_diagnostics_data": "IC 周期诊断数据（JSON）",
    "ic_period_diagnostics_receipt": "IC 周期诊断生成说明（JSON）",
    "ic_quantile_portfolio_statistics_csv": "IC 分组组合统计表（CSV）",
    "ic_quantile_portfolio_statistics_data": "IC 分组组合统计数据（JSON）",
    "ic_quantile_portfolio_statistics_receipt": "IC 分组组合统计生成说明（JSON）",
    "ic_resample_stability_csv": "IC 重采样稳定性表（CSV）",
    "ic_resample_stability_data": "IC 重采样稳定性数据（JSON）",
    "ic_resample_stability_receipt": "IC 重采样稳定性生成说明（JSON）",
    "ic_autocorrelation_csv": "IC 自相关表（CSV）",
    "ic_autocorrelation_data": "IC 自相关数据（JSON）",
    "ic_autocorrelation_receipt": "IC 自相关生成说明（JSON）",
    "ic_holding_half_life_report": "真实持有期 IC 半衰期图（SVG）",
    "ic_holding_half_life_data": "真实持有期 IC 半衰期数据（JSON）",
    "ic_holding_half_life_receipt": "真实持有期 IC 半衰期生成说明（JSON）",
}

_ARTIFACT_DESCRIPTIONS.update(BACKTEST_TABLE_DESCRIPTIONS)


def output_capabilities() -> list[dict[str, Any]]:
    capabilities: list[dict[str, Any]] = []
    for name, value in OUTPUT_DEFINITIONS.items():
        definition = {"name": name, **dict(value)}
        definition["required_sources"] = [
            {
                "name": source,
                "label": _ARTIFACT_DESCRIPTIONS.get(source, source),
            }
            for source in value.get("requires") or ()
        ]
        capabilities.append(definition)
    return capabilities


def _expanded_output_names(requests: Iterable[str]) -> list[str]:
    """Expand aggregate requests using the output definition registry.

    Derived IC tables used to be appended by a second procedural list in
    ``output_declarations``.  ``auto_when`` keeps the relationship beside the
    canonical definition so capabilities, declarations, and artifact lookup
    cannot silently drift apart.
    """

    normalized = normalize_output_requests(list(requests))
    expanded: list[str] = []
    for name in normalized:
        if name not in expanded:
            expanded.append(name)
        for candidate, definition in OUTPUT_DEFINITIONS.items():
            if definition.get("auto_when") == name and candidate not in expanded:
                expanded.append(candidate)
    return expanded


def _ic_result_tabs_for_requests(requests: Iterable[str]) -> list[dict[str, Any]]:
    # Import lazily: the tester settings package composes its application
    # registries at import time, so importing its IC registration slice from
    # this low-level report-definition module would create a cycle.
    from tools.testers.ic_test.result_projection_contract import (
        ic_result_projection_contracts,
    )

    requested = set(requests)
    if not requested:
        return []
    return [
        {
            **projection,
            "source_artifacts": list(projection["source_artifacts"]),
            "output_requests": list(projection["output_requests"]),
        }
        for projection in ic_result_projection_contracts()
        if requested.intersection(projection["output_requests"])
    ]


def output_declarations(requests: Iterable[str]) -> list[dict[str, Any]]:
    """Return the viewer contract stored with a Job detail response."""
    declarations = []
    expanded_names = _expanded_output_names(requests)
    for name in expanded_names:
        definition = OUTPUT_DEFINITIONS[name]
        declaration = {
            "name": name,
            "label": definition["label"],
            "presentation": definition["presentation"],
            "viewer": definition["viewer"],
            "formats": list(definition["formats"]),
            "artifacts": list(definition["artifacts"]),
            "before_run": bool(definition.get("before_run")),
            "after_run": bool(definition.get("after_run")),
            "required_sources": [
                {
                    "name": source,
                    "label": _ARTIFACT_DESCRIPTIONS.get(source, source),
                }
                for source in definition.get("requires") or ()
            ],
            "result_retention_mode": str(
                definition.get("result_retention_mode") or "summary"
            ),
        }
        if definition.get("canonical_artifact"):
            declaration.update({
                "canonical_artifact": definition["canonical_artifact"],
                "rendition_artifacts": list(
                    definition.get("rendition_artifacts") or ()
                ),
                "receipt_artifact": definition["receipt_artifact"],
            })
        for key in (
            "result_surface", "result_view", "supplemental_bundle", "result_order",
        ):
            if key in definition:
                declaration[key] = definition[key]
        declarations.append(declaration)
    ic_names = [
        name for name in expanded_names
        if "ic" in (OUTPUT_DEFINITIONS[name].get("analyses") or ())
    ]
    result_tabs = _ic_result_tabs_for_requests(ic_names)
    if result_tabs:
        first_ic = next(
            item for item in declarations
            if item["name"] in ic_names
        )
        first_ic["result_tabs"] = result_tabs
    return declarations


def artifact_description(name: str) -> str:
    return _ARTIFACT_DESCRIPTIONS.get(str(name), "Job 生成物")


def normalize_output_requests(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, list):
        raise TypeError("output_requests must be an array of names")
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


def output_requests_for_artifacts(artifacts: Iterable[str]) -> list[str]:
    """Recover viewer declarations for outputs generated after a Job run."""
    recovered: list[str] = []
    for raw in artifacts:
        artifact = str(raw or "").strip()
        if not artifact:
            continue
        # Prefer the most specific output-name prefix.  This matters for
        # ic_statistics versus its derived category declarations,
        # whose derived artifacts are also declared by the aggregate request.
        prefixed = [
            name for name in OUTPUT_DEFINITIONS
            if artifact == name or artifact.startswith(f"{name}_")
        ]
        explicit_owner = next(
            (
                OUTPUT_DEFINITIONS[name].get("artifact_owner")
                for name in prefixed
                if OUTPUT_DEFINITIONS[name].get("artifact_owner")
            ),
            "",
        )
        owner = explicit_owner or (max(prefixed, key=len) if prefixed else next((
            name for name, definition in OUTPUT_DEFINITIONS.items()
            if artifact in (definition.get("artifacts") or ())
        ), ""))
        if owner and owner not in recovered:
            recovered.append(owner)
    return recovered


def source_artifacts_for(requests: Iterable[str]) -> set[str]:
    return {
        str(source)
        for name in requests
        for source in OUTPUT_DEFINITIONS.get(str(name), {}).get("requires") or ()
    }


def result_retention_mode_for(
    requests: Iterable[str], *, requested: str = "summary",
) -> str:
    """Return the minimum engine retention required by declared outputs."""
    if str(requested or "summary") == "full":
        return "full"
    normalized = normalize_output_requests(list(requests))
    return "full" if any(
        OUTPUT_DEFINITIONS[name].get("result_retention_mode") == "full"
        for name in normalized
    ) else "summary"
