"""build_report_artifacts must always return a list of generated reports.

A helper inserted at the wrong indentation once swallowed the function body, so
it returned None and the worker crashed with "'NoneType' object is not
iterable"; the return contract is worth a direct guard.
"""

from __future__ import annotations

from server.jobs.report_outputs.builders import build_report_artifacts


def test_factor_series_request_returns_a_list():
    result = {"factor_series": {"schema_version": 1, "factors": [], "series": [
        {"product": "T.CFE", "dates": [1, 2], "values": [0.5, 1.0]},
    ]}}
    reports = build_report_artifacts(result, requested=["factor_series"])
    assert isinstance(reports, list)
    names = {report.name for report in reports}
    assert "factor_series_data" in names
    assert "factor_series_overview_full" in names
    panel = next(report for report in reports if report.name == "factor_series_overview_full")
    assert panel.extension == "png"
    assert panel.content_type == "image/png"
    assert panel.raw.startswith(b"\x89PNG\r\n\x1a\n")


def test_empty_request_still_returns_a_list():
    reports = build_report_artifacts({}, requested=[])
    assert isinstance(reports, list)
