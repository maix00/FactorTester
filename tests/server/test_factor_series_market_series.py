"""The factor-series run must carry the traded product's own OHLCV.

The first implementation called the HTTP price projection, which resolves
products from the Manager catalog and is therefore empty inside a Job worker:
the market chart silently disappeared.  These tests pin the in-process path and
require a *recorded reason* whenever the bars cannot be produced.
"""

from __future__ import annotations

import pandas as pd
import pytest

from server.modules.single_factor_test.evaluation import FactorEvaluation


class _Frequency:
    def __init__(self, name: str, daily: bool = False) -> None:
        self.name = name
        self._daily = daily

    def is_day_multiple(self) -> bool:
        return self._daily

    def __eq__(self, other) -> bool:
        return isinstance(other, _Frequency) and other.name == self.name

    def __hash__(self) -> int:
        return hash(self.name)


class _View:
    """Stand-in for ProductDataView: only the requested columns come back."""

    def __init__(self, frame: pd.DataFrame, failure: Exception | None = None) -> None:
        self.frame = frame
        self.failure = failure
        self.calls: list[list[str]] = []

    def get_and_adjust_cols(self, cols, copy=False, start_dt=None, end_dt=None):
        columns = list(cols)
        self.calls.append(columns)
        missing = [name for name in columns if name not in self.frame.columns]
        if missing:
            raise KeyError(missing[0])
        if self.failure is not None:
            raise self.failure
        return self.frame[columns]


class _Product:
    def __init__(self, name: str, view: _View, frequency: _Frequency) -> None:
        self.name = name
        self.timezone = "Asia/Shanghai"
        self.current_freq = frequency
        self._view = view
        self._frequency = frequency

    def list_available_freqs(self):
        return [self._frequency]

    def __getattr__(self, item: str):
        if item == self._frequency.name:
            return self._view
        raise AttributeError(item)


def _frame(with_interest: bool = True) -> pd.DataFrame:
    index = pd.date_range("2026-05-27 09:30", periods=3, freq="30min", tz="Asia/Shanghai")
    data = {
        "OPEN_ADJUSTED": [104.0, 105.0, 106.0],
        "HIGH_ADJUSTED": [105.0, 106.0, 107.0],
        "LOW_ADJUSTED": [103.0, 104.0, 105.0],
        "CLOSE_ADJUSTED": [104.5, 105.5, 106.5],
        "VOLUME": [10.0, 20.0, 30.0],
    }
    if with_interest:
        data["OPEN_INTEREST"] = [2000.0, 2100.0, 2200.0]
    return pd.DataFrame(data, index=index)


def _evaluation(monkeypatch) -> FactorEvaluation:
    evaluation = FactorEvaluation(
        selection=None, factor_family_alias="family", factor_alias="alias",
        page_uuid="page", settings={"price_type": "adjusted"},
    )
    monkeypatch.setattr(
        FactorEvaluation, "_run_window_datetimes", lambda self: (None, None),
    )
    return evaluation


def test_market_entry_reads_bars_from_the_product_view(monkeypatch):
    view = _View(_frame())
    product = _Product("T.CFE", view, _Frequency("MIN30"))
    entry = _evaluation(monkeypatch)._market_entry(product, True, None, None)

    assert entry["product"] == "T.CFE"
    assert entry["freq"] == "MIN30"
    assert entry["has_open_interest"] is True
    assert len(entry["bars"]) == 3
    bar = entry["bars"][0]
    assert bar["open"] == 104.0 and bar["close"] == 104.5
    assert bar["volume"] == 10.0 and bar["open_interest"] == 2000.0
    assert "timestamp" in bar and "time" in bar
    assert "reason" not in entry


def test_market_entry_keeps_price_bars_when_open_interest_is_missing(monkeypatch):
    view = _View(_frame(with_interest=False))
    product = _Product("T.CFE", view, _Frequency("MIN30"))
    entry = _evaluation(monkeypatch)._market_entry(product, True, None, None)

    assert len(entry["bars"]) == 3
    assert entry["has_open_interest"] is False
    # the OHLCV retry must be attempted without the OI column
    assert "OPEN_INTEREST" in view.calls[0]
    assert view.calls[-1] == [
        "OPEN_ADJUSTED", "HIGH_ADJUSTED", "LOW_ADJUSTED",
        "CLOSE_ADJUSTED", "VOLUME",
    ]
    assert "读取持仓量失败" in entry["reason"]


def test_market_entry_records_why_bars_are_missing(monkeypatch):
    """A broken provider must surface a reason, never an empty silent drop."""
    view = _View(_frame(), failure=RuntimeError("boom"))
    product = _Product("T.CFE", view, _Frequency("MIN30"))
    entry = _evaluation(monkeypatch)._market_entry(product, True, None, None)

    assert entry["bars"] == []
    assert entry["reason"].startswith("读取行情失败")


def test_market_bars_accept_a_multiindex_frame(monkeypatch):
    """A product view may index by (instrument, time); bars must still format."""
    frame = _frame()
    frame.index = pd.MultiIndex.from_arrays(
        [["T2506"] * len(frame), frame.index], names=["instrument", "time"],
    )
    view = _View(frame)
    product = _Product("T.CFE", view, _Frequency("MIN30"))
    entry = _evaluation(monkeypatch)._market_entry(product, True, None, None)

    assert len(entry["bars"]) == 3
    assert entry["bars"][0]["timestamp"] > 0
    assert "reason" not in entry


def test_market_series_skips_other_products(monkeypatch):
    view = _View(_frame())
    product = _Product("TL.CFE", view, _Frequency("MIN30"))
    evaluation = _evaluation(monkeypatch)
    evaluation.product_name = "T.CFE"

    assert evaluation._market_series([product]) == []


@pytest.mark.parametrize("with_interest", [True, False])
def test_market_bars_thin_the_full_range_and_keep_a_native_tail(
    monkeypatch, with_interest,
):
    """全时段抽样 + 近期原分辨率：K线面板才能与各层序列同跨度。"""
    frame = _frame(with_interest)
    evaluation = _evaluation(monkeypatch)
    entry = evaluation._market_bars(
        "T.CFE", frame, True, _Frequency("MIN30"), "", "Asia/Shanghai",
        limit=2, recent=2,
    )
    assert len(entry["bars"]) == 2
    assert "全时段按 1/2 抽样" in entry["reason"]
    # the native-resolution tail spans the same range when the frame is short
    assert entry.get("recent_bars") in (None, entry["bars"]) or len(entry["recent_bars"]) == 2
    assert entry["has_open_interest"] is with_interest
