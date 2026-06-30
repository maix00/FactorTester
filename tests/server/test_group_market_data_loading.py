from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pandas as pd
import pytest

from server.modules.single_factor_test import group as group_module
from tools.data.types import DataColumn


@dataclass(frozen=True)
class _Freq:
    name: str


class _DataTime:
    def __init__(self, value: str):
        self.ts = pd.Timestamp(value)

    def sort_key(self) -> pd.Timestamp:
        return cast(pd.Timestamp, self.ts)


class _View:
    def __init__(self, data: pd.DataFrame, slice_result: pd.DataFrame | None = None):
        self._data = data
        self._slice_result = slice_result

    def get_data(self, copy: bool = False) -> pd.DataFrame:
        return self._data.copy() if copy else self._data

    def get_and_adjust_cols(self, *_args, **_kwargs) -> pd.DataFrame:
        if self._slice_result is not None:
            return self._slice_result
        return self._data.loc[:, [DataColumn.CLOSE.name]]


class _Product:
    current_freq = _Freq("MIN1")

    def __init__(self, name: str, view: _View):
        self.name = name
        self.MIN1 = view

    def __str__(self) -> str:
        return self.name

    def list_available_freqs(self) -> list[_Freq]:
        return [self.current_freq]


def _stub_historical_fields(monkeypatch) -> None:
    monkeypatch.setattr(group_module, "load_market_rule_field_provider", lambda: object())
    monkeypatch.setattr(group_module, "historical_field_frames_for_market_data", lambda *a, **k: {})


def _market_index(trading_day: str, times: list[str]) -> pd.MultiIndex:
    return pd.MultiIndex.from_arrays(
        [
            [pd.Timestamp(trading_day)] * len(times),
            pd.DatetimeIndex(times),
        ],
        names=["trading_day", "trade_time"],
    )


def test_load_raw_market_data_excludes_products_outside_run_window(monkeypatch):
    _stub_historical_fields(monkeypatch)
    old_data = pd.DataFrame(
        {DataColumn.CLOSE.name: [1.0, 2.0]},
        index=_market_index("2012-01-02", ["2012-01-01 21:00", "2012-01-02 09:00"]),
    )
    active_data = pd.DataFrame(
        {DataColumn.CLOSE.name: [10.0, 11.0]},
        index=_market_index("2026-01-05", ["2026-01-05 09:00", "2026-01-05 09:01"]),
    )
    retired = _Product("ER.CZC", _View(old_data, slice_result=pd.DataFrame()))
    active = _Product("AP.CZC", _View(active_data))

    result = group_module._load_raw_market_data_for(
        [retired, active],
        _DataTime("2026-01-05 09:00"),
        _DataTime("2026-01-05 15:00"),
    )

    assert result["included_products"] == (active,)
    assert result["excluded_out_of_range_products"] == ("ER.CZC",)
    assert list(result["raw_prices"].columns) == [active]


def test_load_raw_market_data_raises_for_in_range_missing_close(monkeypatch):
    _stub_historical_fields(monkeypatch)
    in_range_data = pd.DataFrame(
        {DataColumn.CLOSE.name: [1.0]},
        index=_market_index("2026-01-05", ["2026-01-05 09:01"]),
    )
    product = _Product("AP.CZC", _View(in_range_data, slice_result=pd.DataFrame()))

    with pytest.raises(ValueError, match="本地行情缺口"):
        group_module._load_raw_market_data_for(
            [product],
            _DataTime("2026-01-05 09:00"),
            _DataTime("2026-01-05 15:00"),
        )
