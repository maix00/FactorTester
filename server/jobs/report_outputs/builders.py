"""Report artifact builders composed from series, table, and encoders."""

from __future__ import annotations

from typing import Any

from .models import GeneratedReport
from .render import csv_bytes, json_bytes, render_svg
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
    return output


def series_reports(name, series, title):
    receipt = {"schema_version": 1, "artifact_kind": name,
               "series": [{"label": item["label"], "points": len(item["values"])} for item in series]}
    payload = {"schema_version": 1, "artifact_kind": name, "series": series}
    return [
        GeneratedReport(f"{name}_report", render_svg(title, series, percent=name == "returns_over_time"), "svg", "image/svg+xml", receipt),
        GeneratedReport(f"{name}_data", json_bytes(payload), "json", "application/json", receipt),
    ]


def metrics_reports(series):
    rows = metrics_rows(series)
    receipt = {"schema_version": 1, "artifact_kind": "metrics_over_time", "row_count": len(rows),
               "metrics": ["period_return", "cumulative_return", "drawdown", "rolling_sharpe_60", "rolling_volatility_60"]}
    metric_series = [{"label": item["label"], "timestamps": item["timestamps"],
                      "values": [row["rolling_sharpe_60"] or 0.0 for row in rows if row["series"] == item["label"]]}
                     for item in series]
    return [
        GeneratedReport("metrics_over_time_report", render_svg("指标随时间变化", metric_series), "svg", "image/svg+xml", receipt),
        GeneratedReport("metrics_over_time_data", json_bytes({"schema_version": 1, "rows": rows}), "json", "application/json", receipt),
    ]


def table_reports(name, rows):
    receipt = {"schema_version": 1, "artifact_kind": name, "row_count": len(rows),
               "columns": sorted({key for row in rows for key in row if key != "raw"})}
    return [
        GeneratedReport(f"{name}_csv", csv_bytes(rows), "csv", "text/csv; charset=utf-8", receipt),
        GeneratedReport(f"{name}_data", json_bytes({"schema_version": 1, "rows": rows}), "json", "application/json", receipt),
    ]
