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


def test_artifact_titles_are_reader_facing():
    from tools.cli.release.research_reporting.job_artifact_mounts import (
        artifact_label,
    )
    assert artifact_label("factor_series_overview_full", {}) == "因子值序列与行情（全时段）"
    assert artifact_label("factor_series_overview_intraday", {}) == "因子值序列与行情（最近交易日日内）"
    assert artifact_label("factor_series_overview_hourly", {}) == "因子值序列与行情（小时级）"
    assert artifact_label("factor_series_summary_csv", {}) == "结果概览（CSV）"
    # an explicit description always wins, and unknown names stay verbatim
    assert artifact_label("anything", {"description": "自定义标题"}) == "自定义标题"
    assert artifact_label("unknown_artifact", {}) == "unknown_artifact"


def test_unrelated_artifacts_stay_unmounted():
    assert mount_kind("factor_series_data", {
        "name": "factor_series_data", "content_type": "application/json",
    }) is None
    assert mount_kind("strategy_analysis_source", {
        "name": "strategy_analysis_source", "content_type": "application/json",
    }) is None
