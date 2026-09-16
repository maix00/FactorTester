"""The factor-series Job section must mount its numbers, not only its charts.

`job collect-report` mounts an artifact only when `mount_kind` recognises it, so
the result-area table and the market chart have to be in the whitelist.
"""

from __future__ import annotations

from tools.cli.release.research_reporting.job_artifact_mounts import mount_kind


def test_result_area_table_mounts_as_a_table():
    for name in ("factor_series_summary_data", "factor_series_summary_csv"):
        content_type = (
            "application/json" if name.endswith("_data") else "text/csv"
        )
        assert mount_kind(name, {
            "name": name, "content_type": content_type,
        }) == "table"


def test_factor_series_charts_mount_as_images():
    for name in ("factor_series_chart", "factor_series_market_chart"):
        assert mount_kind(name, {
            "name": name, "content_type": "image/svg+xml",
        }) == "image"


def test_unrelated_artifacts_stay_unmounted():
    assert mount_kind("factor_series_data", {
        "name": "factor_series_data", "content_type": "application/json",
    }) is None
    assert mount_kind("strategy_analysis_source", {
        "name": "strategy_analysis_source", "content_type": "application/json",
    }) is None
