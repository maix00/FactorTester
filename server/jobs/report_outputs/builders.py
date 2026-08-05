"""Report artifact builders composed from series, table, and encoders."""

from __future__ import annotations

import re
from typing import Any

from tools.factors.tester_calc.single_factor_test.ic_diagnostics import metric_semantics_catalog
from tools.cli.release.research_reporting.authoring.inline_links import (
    typed_markdown_link,
)

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


def build_report_artifacts(result, *, source=None, requested=(), job_id=None):
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
        output.extend(ic_statistics_reports(result, job_id=job_id))
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


def table_reports(name, rows, *, payload_extra=None, columns=None):
    declared_columns = list(columns) if columns is not None else sorted(
        {key for row in rows for key in row if key != "raw"}
    )
    column_presentations = {}
    if any(row.get("factor_alias") and row.get("factor_ref") for row in rows):
        column_presentations["factor_alias"] = {
            "presentation": "reference",
            "kind": "factor",
            "target_ref_field": "factor_ref",
        }
    receipt = {"schema_version": 1, "artifact_kind": name, "row_count": len(rows),
               "columns": declared_columns,
               "column_presentations": column_presentations}
    json_columns = declared_columns or ["value"]
    payload = {
        "schema_version": 1,
        "artifact_kind": name,
        "columns": json_columns,
        "column_presentations": column_presentations,
        "rows": rows,
    }
    if isinstance(payload_extra, dict):
        payload.update(payload_extra)
    return [
        GeneratedReport(f"{name}_csv", csv_bytes(rows), "csv", "text/csv; charset=utf-8", receipt),
        GeneratedReport(f"{name}_data", json_bytes(payload), "json", "application/json", receipt),
    ]


_IC_STATISTICS_SUMMARY_COLUMNS = [
    "factor", "experiment", "formation_window",
    "forward_return_horizon", "entry_delay_bars", "n_signal_observations",
    "mean_ic", "std_ic", "icir_signal", "t_stat_hac", "ci95_hac_lower",
    "ci95_hac_upper", "hac_status", "direction_rate", "positive_ic_rate",
    "effective_n_capped", "ic_series_acf1", "forward_ic_half_life_status",
    "forward_ic_half_life_exponential_seconds", "source",
]
_FORMATION_WINDOW = re.compile(r"(?:^|\|)N:([^|]+)")


def _summary_link(*, kind: str, target_ref: str, label: str) -> str:
    """Return a typed link, falling back only for legacy malformed refs."""
    label = str(label or target_ref or "未命名")
    try:
        return typed_markdown_link(
            kind=kind, target_ref=str(target_ref), label=label,
        )
    except ValueError:
        # Old locally reconstructed results may carry a non-canonical factor
        # ref.  Do not make the whole Job artifact invalid; current server
        # factor refs are versioned and therefore produce the typed link.
        return label


def _formation_window(alias: str) -> str:
    match = _FORMATION_WINDOW.search(str(alias))
    return match.group(1) if match else ""


def ic_statistics_summary_rows(
    result: dict[str, Any], *, job_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project the full IC diagnostics into the single report-facing table.

    The raw ``ic_statistics_*`` artifacts remain the canonical, full-width
    diagnostics.  This projection deliberately keeps one representative
    column per diagnostic family and turns factor, Job, and raw-source
    identities into portable report links.
    """
    rows: list[dict[str, Any]] = []
    job_ref = f"job:{job_id}" if job_id else ""
    raw_ref = f"job-artifact:{job_id}:ic_statistics_data" if job_id else ""
    for raw in ic_statistics_rows(result):
        alias = str(raw.get("factor_alias") or "")
        factor_ref = str(raw.get("factor_ref") or "")
        row = {
            "factor": (
                _summary_link(kind="factor", target_ref=factor_ref, label=alias)
                if factor_ref else alias
            ),
            "experiment": (
                _summary_link(kind="job", target_ref=job_ref, label=f"Job {job_id}")
                if job_ref else ""
            ),
            "formation_window": _formation_window(alias),
            "forward_return_horizon": raw.get("forward_return_horizon"),
            "entry_delay_bars": raw.get("entry_delay_bars"),
            "n_signal_observations": raw.get("n_signal_observations"),
            "mean_ic": raw.get("mean_ic"),
            "std_ic": raw.get("std_ic"),
            "icir_signal": raw.get("icir_signal"),
            "t_stat_hac": raw.get("t_stat_hac"),
            "ci95_hac_lower": raw.get("ci95_hac_lower"),
            "ci95_hac_upper": raw.get("ci95_hac_upper"),
            "hac_status": raw.get("hac_status"),
            "direction_rate": raw.get("direction_rate"),
            "positive_ic_rate": raw.get("positive_ic_rate"),
            "effective_n_capped": raw.get("effective_n_capped"),
            "ic_series_acf1": raw.get("ic_series_acf1"),
            "forward_ic_half_life_status": raw.get("forward_ic_half_life_status"),
            "forward_ic_half_life_exponential_seconds": raw.get(
                "forward_ic_half_life_exponential_seconds"
            ),
            "source": (
                _summary_link(
                    kind="artifact", target_ref=raw_ref,
                    label="原始 IC 统计 artifact",
                )
                if raw_ref else ""
            ),
        }
        rows.append(row)
    return rows


def ic_statistics_summary_reports(result, *, job_id=None):
    """Build the one curated report-table artifact for IC statistics."""
    rows = ic_statistics_summary_rows(result, job_id=job_id)
    payload_extra = {
        "artifact_role": "report_table",
        "source_artifacts": [
            "ic_statistics_csv", "ic_statistics_data",
        ],
        "column_semantics": {
            "factor": "factor identity link",
            "experiment": "Job identity link",
            "formation_window": "N window parsed from factor alias",
            "mean_ic": "mean cross-sectional rank IC",
            "std_ic": "IC time-series standard deviation",
            "icir_signal": "mean IC divided by IC standard deviation",
            "t_stat_hac": "HAC-adjusted t statistic",
            "ci95_hac_lower": "lower endpoint of the HAC 95% interval",
            "ci95_hac_upper": "upper endpoint of the HAC 95% interval",
            "direction_rate": "fraction aligned with expected direction",
            "positive_ic_rate": "fraction of positive IC observations",
            "effective_n_capped": "HAC effective observation count capped at N",
            "ic_series_acf1": "lag-one IC-series autocorrelation",
            "forward_ic_half_life_status": "forward-horizon half-life fit status",
            "forward_ic_half_life_exponential_seconds": "estimated forward-horizon IC half-life in seconds",
            "source": "link to the complete raw IC statistics artifact",
        },
        "link_columns": ["factor", "experiment", "source"],
        "job_id": str(job_id or ""),
    }
    return table_reports(
        "ic_statistics_summary", rows,
        columns=_IC_STATISTICS_SUMMARY_COLUMNS,
        payload_extra=payload_extra,
    )


def ic_statistics_reports(result, *, job_id=None):
    """Build full IC diagnostics plus the single curated report table."""

    reports = table_reports(
        "ic_statistics",
        ic_statistics_rows(result),
        payload_extra={
            "ic_diagnostics_schema": result.get("ic_diagnostics_schema", "ic-diagnostics-v1"),
            "ic_metric_semantics": result.get("ic_metric_semantics") or metric_semantics_catalog(),
            "ic_metric_selection": result.get("ic_metric_selection"),
            "forward_horizon_sampling": result.get("forward_horizon_sampling"),
        },
    )
    reports.extend(ic_statistics_summary_reports(result, job_id=job_id))
    return reports


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
        "ic_metric_selection": result.get("ic_metric_selection"),
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
        "ic_metric_selection": receipt["ic_metric_selection"],
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
