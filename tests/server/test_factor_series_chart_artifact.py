"""The factor-series output carries a mountable chart of every layer.

A JSON-only output left an auto-mounted job section with nothing to show, so the
rendition artifact and the whitelist entry are part of the contract.  The chart
must also be a *passive* SVG: the report mounter refuses any SVG that keeps the
XML prolog/DOCTYPE or carries active content.
"""

from __future__ import annotations

import re

from server.jobs.report_outputs.builders import (
    _render_factor_series_chart,
    _render_market_chart,
)
from server.jobs.report_outputs.definitions import OUTPUT_DEFINITIONS

FORBIDDEN = ("<script", "<foreignobject", "<!doctype", "<!entity", "javascript:")


def _payload():
    return {"series": [
        {"product": "T.CFE", "dates": [1, 2, 3], "values": [1.0, 2.0, 1.5]},
        {"product": "T.CFE", "layer": "当日差持续期", "dates": [1, 2, 3], "values": [0.0, 1.0, 2.0]},
    ]}


def test_factor_series_declares_a_rendition_chart():
    definition = OUTPUT_DEFINITIONS["factor_series"]
    assert "factor_series_chart" in definition["artifacts"]
    assert "factor_series_chart" in definition["rendition_artifacts"]
    assert "svg" in definition["formats"]


def test_every_series_entry_becomes_a_panel():
    svg = _render_factor_series_chart(_payload())
    # 2 nested subplots for two entries
    assert svg.count(b"<g id=") >= 2


def test_chart_svg_is_passive_so_the_mounter_accepts_it():
    """裸 XML 序言/DOCTYPE 会让挂载失败:「无法挂载: SVG 含有主动内容」。"""
    text = _render_factor_series_chart(_payload()).decode("utf-8")
    lowered = text.lower()
    assert text.lstrip().startswith("<svg")
    assert not any(token in lowered for token in FORBIDDEN)
    assert not re.search(
        r"(?:href|src)\s*=\s*[\"']\s*(?:https?:|file:|javascript:)", lowered,
    )
    assert not re.search(r"\son[a-z]+\s*=", text)


def test_render_is_empty_without_series():
    assert _render_factor_series_chart({"series": []}) == b""
    assert _render_factor_series_chart({}) == b""


def _market_payload(open_interest=True):
    bars = []
    for index in range(6):
        bar = {
            "time": f"2026-05-2{index}T01:30:00+00:00",
            "timestamp": 1779000000000 + index * 60000,
            "open": 105.0 + index, "high": 106.0 + index,
            "low": 104.0 + index, "close": 105.5 + index,
            "volume": 1000.0 + index,
        }
        if open_interest:
            bar["open_interest"] = 20000.0 + index * 10
        bars.append(bar)
    return {"market": [{
        "product": "T.CFE", "freq": "MIN1", "adjusted": True,
        "has_open_interest": open_interest, "bars": bars,
    }]}


def test_factor_series_declares_a_market_chart_rendition():
    definition = OUTPUT_DEFINITIONS["factor_series"]
    assert "factor_series_market_chart" in definition["artifacts"]
    assert "factor_series_market_chart" in definition["rendition_artifacts"]


def test_market_chart_draws_price_volume_and_open_interest():
    svg = _render_market_chart(_market_payload())
    text = svg.decode("utf-8")
    assert text.lstrip().startswith("<svg")
    assert "K线" in text and "成交量" in text and "持仓量" in text


def test_market_chart_drops_the_open_interest_panel_when_absent():
    text = _render_market_chart(_market_payload(open_interest=False)).decode("utf-8")
    assert "持仓量" not in text


def test_market_chart_is_passive():
    text = _render_market_chart(_market_payload()).decode("utf-8")
    lowered = text.lower()
    assert not any(token in lowered for token in FORBIDDEN)
    assert not re.search(r"\son[a-z]+\s*=", text)


def test_market_chart_is_empty_without_bars():
    assert _render_market_chart({}) == b""
    assert _render_market_chart({"market": []}) == b""
    assert _render_market_chart({"market": [{"bars": []}]}) == b""
