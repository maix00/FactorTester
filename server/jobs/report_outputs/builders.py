"""Report artifact builders composed from series, table, and encoders."""

from __future__ import annotations

from typing import Any, Callable

from tools.factors.tester_calc.single_factor_test.ic_diagnostics import metric_semantics_catalog
from tools.cli.release.research_reporting.authoring.inline_links import (
    typed_markdown_link,
)

from .models import GeneratedReport
from .dataset import ReportDataset
from .ic import (
    ic_holding_half_life_rows,
    ic_series,
    ic_statistics_rows,
    quantile_portfolio_statistics_rows,
)
from .ic_rolling import (
    ROLLING_STABILITY_COLUMNS,
    rolling_stability_payload_extra,
    rolling_stability_rows,
)
from .ic_period import (
    PERIOD_DIAGNOSTICS_COLUMNS,
    period_diagnostics_payload_extra,
    period_diagnostics_rows,
)
from .render import csv_bytes, json_bytes
from .series_plot import (
    render_holding_half_life_svg,
    render_metrics_svg,
    render_series_svg,
)
from .series import metrics_rows


def build_report_artifacts(
    result,
    *,
    source=None,
    requested=(),
    job_id=None,
    progress: Callable[[int, int, str], None] | None = None,
):
    result = result if isinstance(result, dict) else {}
    source = source if isinstance(source, dict) else {}
    names = list(dict.fromkeys(str(item) for item in requested)) or ["equity_curve"]
    dataset = ReportDataset(result, source)
    completed: set[str] = set()

    def done(name: str) -> None:
        completed.add(name)
        if progress is not None:
            progress(len(completed), len(names), name)

    series = dataset.series if set(names) & {
        "equity_curve", "returns_over_time", "metrics_over_time",
        "ratio_detail", "drawdown_detail", "period_returns",
    } else []
    output = []
    if "equity_curve" in names and series:
        output.extend(series_reports("equity_curve", series, "净值曲线与回撤"))
    if "equity_curve" in names:
        done("equity_curve")
    if "returns_over_time" in names and series:
        output.extend(series_reports("returns_over_time", dataset.returns, "收益率随时间变化"))
    if "returns_over_time" in names:
        done("returns_over_time")
    if "metrics_over_time" in names and series:
        output.extend(metrics_reports(series))
    if "metrics_over_time" in names:
        done("metrics_over_time")
    if "fee_detail" in names:
        output.extend(table_reports("fee_detail", dataset.fees))
        done("fee_detail")
    if "margin_detail" in names:
        output.extend(table_reports("margin_detail", dataset.margins))
        done("margin_detail")
    if "ratio_detail" in names:
        output.extend(table_reports("ratio_detail", dataset.ratios))
        done("ratio_detail")
    table_datasets = {
        "order_detail": lambda: dataset.orders,
        "fill_detail": lambda: dataset.fills,
        "cash_detail": lambda: dataset.cash,
        "position_detail": lambda: dataset.positions,
        "exposure_detail": lambda: dataset.exposures,
        "turnover_detail": lambda: dataset.turnover,
        "drawdown_detail": lambda: dataset.drawdowns,
        "period_returns": lambda: dataset.period_returns,
    }
    for name, load_rows in table_datasets.items():
        if name in names:
            output.extend(table_reports(name, load_rows()))
            done(name)
    if "ic_series" in names:
        output.extend(series_reports("ic_series", ic_series(result), "IC 序列"))
        done("ic_series")
    if "ic_statistics" in names:
        output.extend(ic_statistics_reports(result, job_id=job_id))
        done("ic_statistics")
    elif "ic_quantile_portfolio_statistics" in names:
        output.extend(ic_quantile_portfolio_statistics_reports(result, job_id=job_id))
        done("ic_quantile_portfolio_statistics")
    if "ic_rolling_stability" in names or "ic_statistics" in names:
        output.extend(ic_rolling_stability_reports(result, job_id=job_id))
        if "ic_rolling_stability" in names:
            done("ic_rolling_stability")
    if "ic_period_diagnostics" in names or "ic_statistics" in names:
        output.extend(ic_period_diagnostics_reports(result, job_id=job_id))
        if "ic_period_diagnostics" in names:
            done("ic_period_diagnostics")
    if "ic_holding_half_life" in names:
        output.extend(ic_holding_half_life_plot(result))
        done("ic_holding_half_life")
    for name in names:
        if name not in completed:
            done(name)
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
        compacted = {**item}
        for key, value in item.items():
            if isinstance(value, list) and len(value) == len(values):
                compacted[key] = [value[index] for index in indices]
        compacted["values"] = [values[index] for index in indices]
        compacted["timestamps"] = [timestamps[index] for index in indices]
        if len(timestamps) < len(values):
            compacted["timestamps"] = timestamps
        output.append(compacted)
    return output


def table_reports(name, rows, *, payload_extra=None, columns=None):
    declared_columns = list(columns) if columns is not None else list(dict.fromkeys(
        key for row in rows for key in row if key != "raw"
    ))
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
        for key in ("artifact_role", "source_artifacts", "link_columns", "aggregation"):
            if key in payload_extra:
                receipt[key] = payload_extra[key]
    return [
        GeneratedReport(
            f"{name}_csv", csv_bytes(rows, columns=declared_columns),
            "csv", "text/csv; charset=utf-8", receipt,
        ),
        GeneratedReport(f"{name}_data", json_bytes(payload), "json", "application/json", receipt),
    ]


_IC_STATISTICS_SUMMARY_COLUMNS = [
    "factor", "experiment", "entry_delay_bars",
    "primary_forward_return_horizon", "n_horizons",
    "n_signal_observations_primary", "mean_ic_primary", "std_ic_primary",
    "icir_signal_primary", "t_stat_hac_primary", "ci95_hac_lower_primary",
    "ci95_hac_upper_primary", "hac_status_primary", "direction_rate_primary",
    "positive_ic_rate_primary", "effective_n_capped_primary",
    "ic_series_acf1_primary", "forward_ic_half_life_status",
    "forward_ic_half_life_registered_direction",
    "forward_ic_half_life_observed_direction",
    "forward_ic_half_life_direction_match",
    "forward_ic_half_life_direction_status",
    "forward_ic_half_life_exponential_seconds", "source",
]

_IC_HALF_LIFE_DIRECTION_COLUMN_SEMANTICS = {
    "forward_ic_half_life_registered_direction": (
        "pre-registered factor direction used for the IC direction convention"
    ),
    "forward_ic_half_life_observed_direction": (
        "sign of the observed baseline forward IC used to orient the half-life curve"
    ),
    "forward_ic_half_life_direction_match": (
        "whether the pre-registered and observed half-life directions agree; "
        "null when either is unavailable"
    ),
    "forward_ic_half_life_direction_status": (
        "match, mismatch, or not_comparable for the two directions"
    ),
}
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


def _first_present(rows: list[dict[str, Any]], key: str) -> Any:
    for row in rows:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def ic_statistics_summary_rows(
    result: dict[str, Any], *, job_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project the full IC diagnostics into the single report-facing table.

    The raw ``ic_statistics_*`` artifacts remain the canonical, full-width
    diagnostics.  This projection deliberately emits one row per
    factor/IC-method/entry-delay.  Horizon-specific statistics come from the
    factor's declared primary horizon; the half-life fields are fitted over
    all available horizon means.  It therefore never averages incompatible
    forward-return labels into a fabricated statistic.
    """
    rows: list[dict[str, Any]] = []
    job_ref = f"job:{job_id}" if job_id else ""
    raw_ref = f"job-artifact:{job_id}:ic_statistics_data" if job_id else ""
    factor_metadata: dict[tuple[str, str], dict[str, Any]] = {}
    for factor in result.get("factors") or ():
        if not isinstance(factor, dict):
            continue
        alias = str(factor.get("factor_alias") or factor.get("alias") or "")
        factor_ref = str(factor.get("factor_ref") or "")
        factor_metadata[(factor_ref, alias)] = factor

    grouped: dict[tuple[str, str, str, int], list[dict[str, Any]]] = {}
    for raw in ic_statistics_rows(result):
        key = (
            str(raw.get("factor_ref") or ""),
            str(raw.get("factor_alias") or ""),
            str(raw.get("ic_method") or "rank"),
            int(raw.get("entry_delay_bars") or 0),
        )
        grouped.setdefault(key, []).append(raw)

    for (factor_ref, alias, _ic_method, delay), horizon_rows in grouped.items():
        factor = factor_metadata.get((factor_ref, alias)) or {}
        declared_primary = str(
            factor.get("primary_forward_return_horizon") or ""
        )
        primary_row = next(
            (
                row for row in horizon_rows
                if str(row.get("forward_return_horizon") or "") == declared_primary
            ),
            horizon_rows[0],
        )
        primary_horizon = str(
            primary_row.get("forward_return_horizon") or declared_primary
        )
        horizons = sorted({
            str(row.get("forward_return_horizon") or "")
            for row in horizon_rows
            if str(row.get("forward_return_horizon") or "")
        })
        row = {
            "factor": (
                _summary_link(kind="factor", target_ref=factor_ref, label=alias)
                if factor_ref else alias
            ),
            "experiment": (
                _summary_link(kind="job", target_ref=job_ref, label=f"Job {job_id}")
                if job_ref else ""
            ),
            "entry_delay_bars": delay,
            "primary_forward_return_horizon": primary_horizon,
            "n_horizons": len(horizons),
            "n_signal_observations_primary": primary_row.get(
                "n_signal_observations"
            ),
            "mean_ic_primary": primary_row.get("mean_ic"),
            "std_ic_primary": primary_row.get("std_ic"),
            "icir_signal_primary": primary_row.get("icir_signal"),
            "t_stat_hac_primary": primary_row.get("t_stat_hac"),
            "ci95_hac_lower_primary": primary_row.get("ci95_hac_lower"),
            "ci95_hac_upper_primary": primary_row.get("ci95_hac_upper"),
            "hac_status_primary": primary_row.get("hac_status"),
            "direction_rate_primary": primary_row.get("direction_rate"),
            "positive_ic_rate_primary": primary_row.get("positive_ic_rate"),
            "effective_n_capped_primary": primary_row.get("effective_n_capped"),
            "ic_series_acf1_primary": primary_row.get("ic_series_acf1"),
            "forward_ic_half_life_status": _first_present(
                horizon_rows, "forward_ic_half_life_status"
            ),
            "forward_ic_half_life_registered_direction": _first_present(
                horizon_rows, "forward_ic_half_life_registered_direction"
            ),
            "forward_ic_half_life_observed_direction": _first_present(
                horizon_rows, "forward_ic_half_life_observed_direction"
            ),
            "forward_ic_half_life_direction_match": _first_present(
                horizon_rows, "forward_ic_half_life_direction_match"
            ),
            "forward_ic_half_life_direction_status": _first_present(
                horizon_rows, "forward_ic_half_life_direction_status"
            ),
            "forward_ic_half_life_exponential_seconds": _first_present(
                horizon_rows, "forward_ic_half_life_exponential_seconds"
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
            "entry_delay_bars": "entry delay; one row is retained per delay",
            "primary_forward_return_horizon": "horizon used for horizon-specific point estimates",
            "n_horizons": "number of distinct forward horizons in the grouped row",
            "n_signal_observations_primary": "signal count at the primary horizon",
            "mean_ic_primary": "mean cross-sectional rank IC at the primary horizon",
            "std_ic_primary": "IC time-series standard deviation at the primary horizon",
            "icir_signal_primary": "mean IC divided by IC standard deviation at the primary horizon",
            "t_stat_hac_primary": "HAC-adjusted t statistic at the primary horizon",
            "ci95_hac_lower_primary": "lower endpoint of the HAC 95% interval at the primary horizon",
            "ci95_hac_upper_primary": "upper endpoint of the HAC 95% interval at the primary horizon",
            "hac_status_primary": "HAC status at the primary horizon",
            "direction_rate_primary": "fraction aligned with expected direction at the primary horizon",
            **_IC_HALF_LIFE_DIRECTION_COLUMN_SEMANTICS,
            "positive_ic_rate_primary": "fraction of positive IC observations at the primary horizon",
            "effective_n_capped_primary": "HAC effective observation count capped at N at the primary horizon",
            "ic_series_acf1_primary": "lag-one IC-series autocorrelation at the primary horizon",
            "forward_ic_half_life_status": "forward-horizon half-life fit status",
            "forward_ic_half_life_exponential_seconds": "estimated forward-horizon IC half-life in seconds",
            "source": "link to the complete raw IC statistics artifact",
        },
        "aggregation": {
            "row_key": ["factor_ref", "factor_alias", "ic_method", "entry_delay_bars"],
            "horizon_grouping": "distinct forward_return_horizon values are grouped into one row",
            "primary_horizon": "factor.primary_forward_return_horizon; first available horizon is the fallback",
            "horizon_specific_statistics": "copied from the primary horizon; never averaged across incompatible labels",
            "half_life": "fit over all available horizon-level mean IC values",
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

    full_rows = ic_statistics_rows(result)
    reports = table_reports(
        "ic_statistics",
        full_rows,
        payload_extra={
            "ic_diagnostics_schema": result.get("ic_diagnostics_schema", "ic-diagnostics-v1"),
            "ic_metric_semantics": result.get("ic_metric_semantics") or metric_semantics_catalog(),
            "ic_metric_selection": result.get("ic_metric_selection"),
            "forward_horizon_sampling": result.get("forward_horizon_sampling"),
            "column_semantics": _IC_HALF_LIFE_DIRECTION_COLUMN_SEMANTICS,
        },
        columns=ordered_ic_statistics_columns(full_rows),
    )
    reports.extend(ic_statistics_summary_reports(result, job_id=job_id))
    quick_rows = quantile_portfolio_statistics_rows(result)
    if quick_rows:
        reports.extend(table_reports(
            "ic_quantile_portfolio_statistics",
            quick_rows,
            payload_extra={
                "artifact_role": "ic_statistics_category",
                "category": "quantile_portfolio_statistics",
                "source_artifacts": ["ic_statistics_data"],
                "column_semantics": {
                    "portfolio_mode": "no_fee or fee_margin_target",
                    "portfolio_kind": "one quantile group or equal-weight top-minus-bottom",
                    "total_return": "canonical grouped-backtest metric, percent",
                    "max_drawdown": "canonical grouped-backtest metric, percent",
                    "sharpe_ratio": "canonical grouped-backtest metric",
                    "monotonic_period_ratio": "fraction of comparable periods whose group returns are monotonic",
                    "initial_capital": "normalized decimal unit equity, not currency",
                    "source_scope": "primary row uses the factor-declared forward-return panel; non-primary rows identify their realized horizon/delay panel",
                    "fee_semantics": "proportional open/close fee rates; fixed-currency fees omitted",
                    "margin_semantics": "non-margin products use margin rate 1.0; no event hard-cap enforcement",
                    "target_margin_utilization": "fixed normalized margin budget used only by fee_margin_target mode",
                    "avg_turnover": "mean absolute target notional-weight change per period, decimal proxy",
                    "turnover_proxy": "mean group target-weight turnover proxy across groups",
                    "long_short_turnover_proxy": "top-minus-bottom target-weight turnover proxy",
                    "turnover_semantics": "explicit proxy semantics; excludes fills, lots, liquidity and fixed fees",
                },
            },
        ))
    return reports


def ic_quantile_portfolio_statistics_reports(result, *, job_id=None):
    """Build only the vectorized portfolio category on a later request."""
    rows = quantile_portfolio_statistics_rows(result)
    if not rows:
        return []
    return table_reports(
        "ic_quantile_portfolio_statistics",
        rows,
        payload_extra={
            "artifact_role": "ic_statistics_category",
            "category": "quantile_portfolio_statistics",
            "source_artifacts": ["ic_statistics_data"],
            "column_semantics": {
                "portfolio_mode": "no_fee or fee_margin_target",
                "portfolio_kind": "one quantile group or equal-weight top-minus-bottom",
                "total_return": "canonical grouped-backtest metric, percent",
                "max_drawdown": "canonical grouped-backtest metric, percent",
                "sharpe_ratio": "canonical grouped-backtest metric",
                "monotonic_period_ratio": "fraction of comparable periods whose group returns are monotonic",
                "initial_capital": "normalized decimal unit equity, not currency",
                "source_scope": "primary row uses the factor-declared forward-return panel; non-primary rows identify their realized horizon/delay panel",
                "fee_semantics": "proportional open/close fee rates; fixed-currency fees omitted",
                "margin_semantics": "non-margin products use margin rate 1.0; no event hard-cap enforcement",
                "target_margin_utilization": "fixed normalized margin budget used only by fee_margin_target mode",
                "avg_turnover": "mean absolute target notional-weight change per period, decimal proxy",
                "turnover_proxy": "mean group target-weight turnover proxy across groups",
                "long_short_turnover_proxy": "top-minus-bottom target-weight turnover proxy",
                "turnover_semantics": "explicit proxy semantics; excludes fills, lots, liquidity and fixed fees",
            },
        },
    )


def ic_rolling_stability_reports(result, *, job_id=None):
    """Build the independent rolling-window stability report table."""

    rows = rolling_stability_rows(result)
    if not rows:
        # A default IC result may have no rolling request.  Do not publish an
        # empty table; the declaration remains available for requested runs.
        return []
    return table_reports(
        "ic_rolling_stability", rows,
        payload_extra=rolling_stability_payload_extra(job_id=job_id),
        columns=ROLLING_STABILITY_COLUMNS,
    )


def ic_period_diagnostics_reports(result, *, job_id=None):
    """Build the independent calendar-period IC diagnostics table."""

    rows = period_diagnostics_rows(result, job_id=job_id)
    if not rows:
        return []
    return table_reports(
        "ic_period_diagnostics", rows,
        payload_extra=period_diagnostics_payload_extra(job_id=job_id),
        columns=PERIOD_DIAGNOSTICS_COLUMNS,
    )


def ordered_ic_statistics_columns(rows: list[dict[str, Any]]) -> list[str]:
    """Order full IC diagnostics by research meaning, not field spelling."""
    present = {key for row in rows for key in row if key != "raw"}
    groups = [
        # identity and horizon context
        ["factor_alias", "factor_ref", "ic_method", "forward_return_horizon", "entry_delay_bars"],
        ["diagnostics_schema", "n_signal_observations", "period_estimability"],
        # point estimate and dispersion
        ["mean_ic", "median_ic", "std_ic", "std_ic_ddof", "mad_ic", "minimum", "maximum", "p10_ic", "p25_ic", "p50_ic", "p75_ic", "p90_ic", "skew_ic", "excess_kurtosis_ic"],
        # inference and direction
        ["se_iid", "ci95_iid_lower", "ci95_iid_upper", "t_stat_iid", "icir_signal", "direction_rate", "expected_sign", "forward_ic_half_life_registered_direction", "forward_ic_half_life_observed_direction", "forward_ic_half_life_direction_match", "forward_ic_half_life_direction_status", "positive_ic_rate", "negative_ic_rate", "zero_ic_rate"],
        ["se_hac", "ci95_hac_lower", "ci95_hac_upper", "t_stat_hac", "hac_status", "hac_reason", "hac_lag", "hac_lag_source", "hac_lag_formula", "hac_kernel", "effective_n_raw", "effective_n_capped", "effective_n_ratio", "effective_n_capped_ratio", "hac_lrv_to_iid_variance_ratio", "ess_exceeds_n"],
        # temporal persistence
        ["ic_series_acf1", "ic_series_acf_half_life_signals", "ic_series_acf_half_life_status", "ic_series_ar1_rho", "ic_series_ar1_r_squared", "ic_series_ar1_half_life_signals", "ic_series_ar1_half_life_seconds", "ic_series_ar1_half_life_status", "ic_series_ar1_n_signal_pairs", "ic_series_ar1_method"],
        # forward-horizon decay and model selection
        ["forward_ic_half_life_status", "forward_ic_half_life_duration", "forward_ic_half_life_crossing_seconds", "forward_ic_half_life_baseline_horizon", "forward_ic_half_life_baseline_seconds", "forward_ic_half_life_baseline_mean_ic", "forward_ic_half_life_expected_direction", "forward_ic_half_life_curve_monotonic_nonincreasing", "forward_ic_half_life_half_amplitude_ic", "forward_ic_half_life_first_crossing_horizon", "forward_ic_half_life_crossing_first_nonpositive_horizon", "forward_ic_half_life_crossing_n_nonpositive_oriented_points"],
        ["forward_ic_half_life_exponential_status", "forward_ic_half_life_exponential_seconds", "forward_ic_half_life_exponential_duration", "forward_ic_half_life_exponential_selected_model", "forward_ic_half_life_exponential_smooth_reversal_model", "forward_ic_half_life_exponential_r_squared", "forward_ic_half_life_exponential_log_fit_rmse", "forward_ic_half_life_exponential_sign_reversal", "forward_ic_half_life_exponential_n_sign_changes", "forward_ic_half_life_exponential_more_horizons_recommended", "forward_ic_half_life_exponential_recommended_min_horizons", "forward_ic_half_life_exponential_recommendation"],
        # audit definitions and compatibility aliases last
        ["hac_overlap_support_seconds", "hac_overlap_support_components_seconds", "ess_definition", "t_stat_hac_reference", "acf_estimator", "ic_method", "std", "ir", "t_stat", "ac1", "half_life"],
    ]
    ordered: list[str] = []
    for group in groups:
        for key in group:
            if key in present and key not in ordered:
                ordered.append(key)
    # Preserve insertion semantics for newly-added metrics; never alphabetize
    # the remainder, which would make the table look semantically random.
    for row in rows:
        for key in row:
            if key != "raw" and key in present and key not in ordered:
                ordered.append(key)
    return ordered


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
