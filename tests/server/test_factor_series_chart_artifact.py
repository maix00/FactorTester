"""The factor-series result area: a plain-language summary table plus PNG panels.

The table is what makes an auto-mounted Job section carry numbers, not only
figures; the PNG panel stacks live in series_overview and are covered by
test_factor_series_overview_png.
"""

from __future__ import annotations

from server.jobs.report_outputs.builders import _series_summary_rows
from server.jobs.report_outputs.definitions import OUTPUT_DEFINITIONS


def _payload():
    return {
        "series": [
            {"product": "T.CFE", "dates": [1, 2, 3], "values": [1.0, 2.0, 1.5]},
            {"product": "T.CFE", "layer": "当日差持续期", "dates": [1, 2, 3],
             "values": [0.0, 1.0, 2.0]},
        ],
        "market": [{
            "product": "T.CFE", "freq": "MIN1", "has_open_interest": True,
            "bars": [
                {"time": "2026-05-27T01:30:00+00:00", "close": 105.0,
                 "volume": 10.0, "open_interest": 2000.0},
                {"time": "2026-05-27T01:31:00+00:00", "close": 105.5,
                 "volume": 12.0, "open_interest": 2100.0},
            ],
        }],
    }


def test_factor_series_declares_the_png_windows_and_the_table():
    definition = OUTPUT_DEFINITIONS["factor_series"]
    for name in ("factor_series_overview_full", "factor_series_overview_intraday",
                 "factor_series_overview_hourly"):
        assert name in definition["artifacts"]
        assert name in definition["rendition_artifacts"]
    assert "factor_series_summary_data" in definition["artifacts"]
    assert "factor_series_summary_csv" in definition["artifacts"]


def test_summary_table_lists_layers_and_market():
    rows = _series_summary_rows(_payload())
    labels = [row["序列"] for row in rows]
    assert "因子值" in labels and "当日差持续期" in labels
    assert any(label.endswith("K线") for label in labels)
    assert any(label.endswith("成交量") for label in labels)
    assert any(label.endswith("持仓量") for label in labels)
    layer = next(row for row in rows if row["序列"] == "当日差持续期")
    assert layer["点数"] == 3 and layer["最新"] == 2.0


def test_summary_table_skips_open_interest_when_absent():
    payload = _payload()
    for bar in payload["market"][0]["bars"]:
        bar.pop("open_interest")
    labels = [row["序列"] for row in _series_summary_rows(payload)]
    assert not any(label.endswith("持仓量") for label in labels)


def test_summary_rows_are_empty_without_data():
    assert _series_summary_rows({}) == []
