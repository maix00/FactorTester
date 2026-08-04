"""Report artifact builders composed from series, table, and encoders."""

from __future__ import annotations

from typing import Any

from tools.factors.tester_calc.single_factor_test.ic_diagnostics import metric_semantics_catalog

from .models import GeneratedReport
from .ic import ic_holding_half_life_rows, ic_series, ic_statistics_rows
from .render import csv_bytes, json_bytes
from .series_plot import (
    render_holding_half_life_svg,
    render_metrics_svg,
    render_series_svg,
)
from .series import extract_series, metrics_rows, return_series
from .tables import fee_rows, margin_rows, ratio_rows


def build_report_artifacts(result, *, source=None, requested=()):
    result = result if isinstance(result, dict) else {}
    source = source if isinstance(source, dict) else {}
    names = list(dict.fromkeys(str(item) for item in requested)) or ["equity_curve"]
    series = extract_series(result, source)
    output = []
    if "equity_curve" in names and series:
        output.extend(series_reports("equity_curve", series, "净值曲线与回撤"))
    if "returns_over_time" in names and series:
        output.extend(series_reports("returns_over_time", return_series(series), "收益率随时间变化"))
    if "metrics_over_time" in names and series:
        output.extend(metrics_reports(series))
    if "fee_detail" in names:
        output.extend(table_reports("fee_detail", fee_rows(source)))
    if "margin_detail" in names:
        output.extend(table_reports("margin_detail", margin_rows(source)))
    if "ratio_detail" in names:
        output.extend(table_reports("ratio_detail", ratio_rows(result, source, series)))
    if "ic_series" in names:
        output.extend(series_reports("ic_series", ic_series(result), "IC 序列"))
    if "ic_statistics" in names:
        output.extend(ic_statistics_reports(result))
    if "ic_holding_half_life" in names:
        output.extend(ic_holding_half_life_plot(result))
    return output


def series_reports(name, series, title):
    receipt = {"schema_version": 1, "artifact_kind": name,
               "series": [{"label": item["label"], "points": len(item["values"])} for item in series]}
    payload_series = series
    if name == "equity_curve":
        payload_series = []
        for item in series:
            peak = float("-inf")
            historical_max = 0.0
            current_drawdowns = []
            historical_drawdowns = []
            for value in item["values"]:
                peak = max(peak, value)
                current = value / peak - 1.0 if peak else 0.0
                historical_max = min(historical_max, current)
                current_drawdowns.append(round(current, 12))
                historical_drawdowns.append(round(historical_max, 12))
            payload_series.append({
                **item,
                "drawdown": current_drawdowns,
                "max_drawdown": historical_drawdowns,
            })
        receipt["drawdown_definition"] = "historical_maximum_drawdown_through_each_point"
    payload = {"schema_version": 1, "artifact_kind": name, "series": payload_series}
    initial_value = (
        series[0]["values"][0] if series and series[0].get("values") else None
    ) if name == "equity_curve" else None
    value_kind = {
        "equity_curve": "currency",
        "returns_over_time": "percent",
        "ic_series": "number",
    }.get(name, "number")
    currency = str(
        next((item.get("currency") for item in series if item.get("currency")), "")
    )
    display_series = _display_series(series)
    return [
        GeneratedReport(
            f"{name}_report",
            render_series_svg(
                title,
                display_series,
                value_kind=value_kind,
                currency=currency,
                reference_value=initial_value,
                reference_label="初始金额" if initial_value is not None else "",
            ),
            "svg",
            "image/svg+xml",
            receipt,
        ),
        GeneratedReport(f"{name}_data", json_bytes(payload), "json", "application/json", receipt),
    ]


def metrics_reports(series):
    rows = metrics_rows(series)
    receipt = {"schema_version": 1, "artifact_kind": "metrics_over_time", "row_count": len(rows),
               "metrics": ["annual_return", "sharpe_ratio", "max_drawdown",
                            "drawdown", "rolling_volatility_60"]}
    metric_series = []
    metric_labels = {
        "annual_return": "年化收益率",
        "sharpe_ratio": "Sharpe ratio",
        "max_drawdown": "历史最大回撤",
        "drawdown": "当前回撤",
        "rolling_volatility_60": "滚动波动率（60期）",
    }
    for metric, label in metric_labels.items():
        for item in series:
            item_rows = [row for row in rows if row["series"] == item["label"]]
            metric_series.append({
                "metric": metric,
                "metric_label": label,
                "label": item["label"],
                "timestamps": item["timestamps"],
                "values": [row.get(metric) or 0.0 for row in item_rows],
            })
    return [
        GeneratedReport(
            "metrics_over_time_report",
            render_metrics_svg("指标随时间变化", _display_series(metric_series)),
            "svg", "image/svg+xml", receipt,
        ),
        GeneratedReport("metrics_over_time_data", json_bytes({"schema_version": 1, "rows": rows}), "json", "application/json", receipt),
    ]


def _display_series(
    series: list[dict[str, Any]], *, maximum: int = 1200,
) -> list[dict[str, Any]]:
    """Bound SVG point counts while retaining the full JSON data artifact."""
    output = []
    for item in series:
        values = list(item.get("values") or ())
        timestamps = list(item.get("timestamps") or ())
        if len(values) <= maximum:
            output.append(item)
            continue
        stride = max(1, (len(values) - 1) // (maximum - 1))
        indices = list(range(0, len(values), stride))
        if indices[-1] != len(values) - 1:
            indices.append(len(values) - 1)
        output.append({
            **item,
            "values": [values[index] for index in indices],
            "timestamps": [timestamps[index] for index in indices]
            if len(timestamps) >= len(values) else timestamps,
        })
    return output


def table_reports(name, rows, *, payload_extra=None):
    column_presentations = {}
    if any(row.get("factor_alias") and row.get("factor_ref") for row in rows):
        column_presentations["factor_alias"] = {
            "presentation": "reference",
            "kind": "factor",
            "target_ref_field": "factor_ref",
        }
    receipt = {"schema_version": 1, "artifact_kind": name, "row_count": len(rows),
               "columns": sorted({key for row in rows for key in row if key != "raw"}),
               "column_presentations": column_presentations}
    payload = {
        "schema_version": 1,
        "column_presentations": column_presentations,
        "rows": rows,
    }
    if isinstance(payload_extra, dict):
        payload.update(payload_extra)
    return [
        GeneratedReport(f"{name}_csv", csv_bytes(rows), "csv", "text/csv; charset=utf-8", receipt),
        GeneratedReport(f"{name}_data", json_bytes(payload), "json", "application/json", receipt),
    ]


def ic_statistics_reports(result):
    """Build the on-demand IC statistics table."""

    return table_reports(
        "ic_statistics",
        ic_statistics_rows(result),
        payload_extra={
            "ic_diagnostics_schema": result.get("ic_diagnostics_schema", "ic-diagnostics-v1"),
            "ic_metric_semantics": result.get("ic_metric_semantics") or metric_semantics_catalog(),
            "forward_horizon_sampling": result.get("forward_horizon_sampling"),
        },
    )


def ic_holding_half_life_plot(result):
    """Build only the parallel, explicitly requested holding-period plot."""

    rows = [
        row for row in ic_holding_half_life_rows(result)
        if int(row.get("n_horizons") or 0) >= 2
    ]
    if not rows:
        return []
    receipt = {
        "schema_version": 1,
        "artifact_kind": "ic_holding_half_life",
        "row_count": len(rows),
        "method": "log_linear_ols_on_precomputed_forward_horizon_mean_ic",
        "complexity": "O(H) per factor/entry-delay after IC horizon means are available",
        "semantics": "true forward holding-period decay; distinct from IC-series ACF/AR(1) persistence",
        "inference": "descriptive_only; no half-life confidence interval is inferred",
        "horizon_overlap_note": "forward-return horizons may overlap; use non-overlapping horizons or a block/bootstrap procedure before inferential use",
        "forward_horizon_sampling": result.get("forward_horizon_sampling"),
        "on_demand": True,
    }
    payload = {
        "schema_version": 1,
        "artifact_kind": "ic_holding_half_life",
        "rows": rows,
        "semantics": receipt["semantics"],
        "method": receipt["method"],
        "inference": receipt["inference"],
        "horizon_overlap_note": receipt["horizon_overlap_note"],
        "forward_horizon_sampling": receipt["forward_horizon_sampling"],
    }
    return [GeneratedReport(
        "ic_holding_half_life_report",
        render_holding_half_life_svg("真实持有期 IC 半衰期", rows),
        "svg", "image/svg+xml", receipt,
    ), GeneratedReport(
        "ic_holding_half_life_data",
        json_bytes(payload), "json", "application/json", receipt,
    )]
