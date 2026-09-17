"""The mounted result area is a PNG panel stack with a real time axis.

Panels: the traded product's K线, every factor layer, 成交量 and (when the
provider exposes it) 持仓量.  Windows: 全时段 always, plus 日内/小时级 when the run
is intraday.  PNG keeps the mounted assets small enough to load quickly.
"""

from __future__ import annotations

from server.jobs.report_outputs.series_overview import (
    available_windows,
    overview_panels,
    panel_titles,
    render_overview_png,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _bars(count: int = 40, sessions: int = 1) -> list[dict]:
    rows = []
    per_session = max(1, count // max(1, sessions))
    for index in range(count):
        day = 27 - (index // per_session)
        rows.append({
            "time": f"2026-05-{day:02d}T02:{index % 60:02d}:00+00:00",
            "timestamp": 1779000000000 + index * 60000,
            "open": 105.0 + index * 0.001, "high": 105.2 + index * 0.001,
            "low": 104.8 + index * 0.001, "close": 105.1 + index * 0.001,
            "volume": 1000.0 + index, "open_interest": 20000.0 + index,
        })
    return rows


def _payload(count: int = 40, sessions: int = 1, layer_name: str = "阈值层", interest: bool = True):
    bars = _bars(count, sessions)
    if not interest:
        for bar in bars:
            bar.pop("open_interest")
    dates = [bar["timestamp"] for bar in bars]
    return {
        "series": [
            {"product": "T.CFE", "dates": dates, "values": [float(i) for i in range(count)]},
            {"product": "T.CFE", "layer": layer_name, "dates": dates,
             "values": [float(count - i) for i in range(count)]},
        ],
        "market": [{
            "product": "T.CFE", "freq": "MIN1", "adjusted": True,
            "has_open_interest": interest, "bars": bars,
        }],
    }


def test_panels_name_every_layer_and_the_market():
    payload = _payload()
    titles = panel_titles(payload, window="full")
    assert titles[0].startswith("T.CFE K线")
    assert "因子层 · 阈值层" in titles
    assert "因子层 · 因子值" in titles
    assert "成交量" in titles and "持仓量" in titles
    # the price panel comes first, then layers, then volume/interest
    assert titles.index("成交量") > titles.index("因子层 · 阈值层")
    order = [kind for kind, _title, _frame in overview_panels(payload, window="full")]
    assert order == ["price", "layer", "layer", "volume", "interest"]


def test_open_interest_panel_is_omitted_when_the_provider_lacks_it():
    titles = panel_titles(_payload(interest=False), window="full")
    assert "持仓量" not in titles
    assert "成交量" in titles


def test_renderer_emits_png():
    assert render_overview_png(_payload(), window="full").startswith(PNG_MAGIC)


def test_windows_follow_the_factor_frequency():
    # one point per session = a daily factor: only the full window makes sense
    assert available_windows(_payload(count=40, sessions=40)) == ["full"]
    # many bars inside several sessions = an intraday factor
    assert available_windows(_payload(count=400, sessions=5)) == [
        "full", "intraday", "hourly",
    ]


def test_intraday_and_hourly_windows_render():
    payload = _payload(count=600, sessions=6)
    assert render_overview_png(payload, window="intraday").startswith(PNG_MAGIC)
    assert render_overview_png(payload, window="hourly").startswith(PNG_MAGIC)


def test_empty_payload_renders_nothing():
    assert render_overview_png({}, window="full") == b""
    assert available_windows({}) == []
    assert panel_titles({}, window="full") == []
