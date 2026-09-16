"""The factor-series output carries a mountable chart of every layer.

A JSON-only output left an auto-mounted job section with nothing to show, so the
rendition artifact and the whitelist entry are part of the contract.  The chart
must also be a *passive* SVG: the report mounter refuses any SVG that keeps the
XML prolog/DOCTYPE or carries active content.
"""

from __future__ import annotations

import re

from server.jobs.report_outputs.builders import _render_factor_series_chart
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
