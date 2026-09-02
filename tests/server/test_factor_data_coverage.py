from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from server.modules.shared.factor_data_coverage import require_factor_data_coverage
from tools.data.types import DataTime


class _View:
    def __init__(self, start: str, end: str) -> None:
        self.frame = pd.DataFrame(
            {"CLOSE": [1.0, 2.0]},
            index=pd.DatetimeIndex([start, end], name="MIN1"),
        )

    def get_data(self, *, copy: bool, source=None):
        return self.frame.copy() if copy else self.frame


def _product(start: str, end: str):
    return SimpleNamespace(name="AP.CZC", MIN1=_View(start, end))


def _factor():
    return SimpleNamespace(family=SimpleNamespace(source_freq="1m"), freq=None)


def _time(value: str) -> DataTime:
    return DataTime(ts=pd.Timestamp(value, tz="Asia/Shanghai"))


def test_factor_data_coverage_accepts_source_covering_requested_dates() -> None:
    require_factor_data_coverage(
        [_product("2024-01-01 09:00", "2025-06-02 15:00")],
        _factor(),
        start_dt=_time("2024-01-02 09:00"),
        end_dt=_time("2025-05-30 15:00"),
    )


def test_factor_data_coverage_rejects_truncated_source_range() -> None:
    with pytest.raises(ValueError, match="数据源未覆盖测试时间范围"):
        require_factor_data_coverage(
            [_product("2025-01-01 09:00", "2025-01-31 15:00")],
            _factor(),
            start_dt=_time("2024-01-02 09:00"),
            end_dt=_time("2025-05-30 15:00"),
        )
