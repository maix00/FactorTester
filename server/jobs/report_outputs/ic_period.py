"""Report-table projection for server-produced IC period diagnostics."""

from __future__ import annotations

from typing import Any

from tools.cli.release.research_reporting.authoring.inline_links import (
    typed_markdown_link,
)


PERIOD_DIAGNOSTICS_COLUMNS = [
    "factor", "experiment", "ic_method", "entry_delay_bars",
    "period_label", "period_rule", "period_start",
    "period_estimable", "hac_estimable",
    "period_min_signal_observations", "period_min_periods",
    "n_periods_total", "n_periods_estimable", "n_periods_hac_estimable",
    "period_estimability_status", "n_signal_observations", "mean_ic",
    "std_ic", "icir_signal", "t_stat_hac", "ci95_hac_lower",
    "ci95_hac_upper", "hac_status", "direction_rate", "positive_ic_rate",
    "effective_n_capped", "ic_series_acf1",
]


def _link(kind: str, target_ref: str, label: str) -> str:
    """Use typed links for current refs, but keep legacy rows readable."""
    if not target_ref:
        return label
    try:
        return typed_markdown_link(
            kind=kind, target_ref=target_ref, label=label or target_ref,
        )
    except ValueError:
        return label or target_ref


def period_diagnostics_rows(
    result: dict[str, Any], *, job_id: str | None = None,
) -> list[dict[str, Any]]:
    """Flatten per-period server diagnostics without recomputing IC values.

    The worker result contains the complete period records.  A persisted
    compact result may contain only period counts/statuses; that representation
    is still projected as one audit row per requested period rule instead of
    silently dropping the non-estimable state.
    """
    rows: list[dict[str, Any]] = []
    job_ref = f"job:{job_id}" if job_id else ""
    try:
        primary_delay = int(
            result.get("primary_entry_delay_bars", result.get("entry_delay_bars", 0))
        )
    except (TypeError, ValueError):
        primary_delay = 0
    for factor in result.get("factors") or ():
        if not isinstance(factor, dict):
            continue
        alias = str(factor.get("factor_alias") or factor.get("alias") or "")
        factor_ref = str(factor.get("factor_ref") or "")
        factor_link = _link("factor", factor_ref, alias)
        experiment_link = _link("job", job_ref, f"Job {job_id}") if job_ref else ""
        method = str(factor.get("ic_method") or "rank")
        period_payload = factor.get("period_diagnostics")
        periods = period_payload.get("periods") if isinstance(period_payload, dict) else None
        if not isinstance(periods, dict):
            continue
        for label, summary in periods.items():
            if not isinstance(summary, dict):
                continue
            records = summary.get("periods")
            if not isinstance(records, list) or not records:
                records = [{}]
            common = {
                "factor": factor_link,
                "experiment": experiment_link,
                "ic_method": method,
                "entry_delay_bars": primary_delay,
                "period_label": str(label),
                "period_rule": summary.get("rule"),
                "period_min_signal_observations": summary.get("min_signal_observations"),
                "period_min_periods": summary.get("min_periods"),
                "n_periods_total": summary.get("n_periods_total"),
                "n_periods_estimable": summary.get("n_periods_estimable"),
                "n_periods_hac_estimable": summary.get("n_periods_hac_estimable"),
                "period_estimability_status": summary.get("period_estimability_status"),
            }
            for record in records:
                record = record if isinstance(record, dict) else {}
                row = {
                    **common,
                    "period_start": record.get("period_start"),
                    "period_estimable": record.get("period_estimable"),
                    "hac_estimable": record.get("hac_estimable"),
                }
                for name in (
                    "n_signal_observations", "mean_ic", "std_ic", "icir_signal",
                    "t_stat_hac", "ci95_hac_lower", "ci95_hac_upper",
                    "hac_status", "direction_rate", "positive_ic_rate",
                    "effective_n_capped", "ic_series_acf1",
                ):
                    row[name] = record.get(name)
                rows.append(row)
    return rows


def period_diagnostics_payload_extra(*, job_id: str | None = None) -> dict[str, Any]:
    return {
        "period_diagnostics_schema": "ic-period-diagnostics-v1",
        "artifact_role": "report_table",
        "source_artifacts": ["ic_statistics_data"],
        "link_columns": ["factor", "experiment"],
        "aggregation": {
            "row_key": [
                "factor", "ic_method", "entry_delay_bars", "period_label",
                "period_start",
            ],
            "window_selector": "calendar_period_diagnostics_only",
            "rolling_selector": "signal_count; not a period rule",
        },
        "job_id": str(job_id or ""),
    }


__all__ = [
    "PERIOD_DIAGNOSTICS_COLUMNS",
    "period_diagnostics_rows",
    "period_diagnostics_payload_extra",
]
