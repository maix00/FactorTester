from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from server.modules.shared.factor_data_coverage import (
    FactorDataCoverageError,
    require_factor_data_coverage,
)
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


def test_factor_data_coverage_preserves_market_wall_clock_date() -> None:
    result = require_factor_data_coverage(
        [_product("2024-01-01 09:00", "2024-01-02 15:00")],
        _factor(),
        start_dt=_time("2024-01-01 00:00"),
        end_dt=_time("2024-01-02 15:00"),
    )

    assert result["formal_start"] == "2024-01-01"


def test_no_warmup_allows_leading_gap_that_will_produce_nan() -> None:
    result = require_factor_data_coverage(
        [_product("2024-01-02 09:00", "2024-01-05 15:00")],
        _factor(),
        start_dt=_time("2024-01-01 00:00"),
        end_dt=_time("2024-01-05 15:00"),
    )

    assert result["required_data_start"] == "2024-01-01"
    assert result["leading_gaps"] == [
        {"product": "AP.CZC", "available_start": "2024-01-02"},
    ]


def test_fixed_warmup_requires_earlier_source_data() -> None:
    with pytest.raises(FactorDataCoverageError) as caught:
        require_factor_data_coverage(
            [_product("2024-01-02 09:00", "2024-01-05 15:00")],
            _factor(),
            start_dt=_time("2024-01-03 00:00"),
            end_dt=_time("2024-01-05 15:00"),
            warmup_window=pd.Timedelta("2D"),
        )

    assert caught.value.code == "factor_data_coverage_unavailable"
    assert caught.value.details["formal_start"] == "2024-01-03"
    assert caught.value.details["required_data_start"] == "2024-01-01"


def test_source_starting_after_formal_end_is_not_eligible() -> None:
    with pytest.raises(FactorDataCoverageError) as caught:
        require_factor_data_coverage(
            [_product("2025-01-02 09:00", "2026-01-05 15:00")],
            _factor(),
            start_dt=_time("2024-01-01 00:00"),
            end_dt=_time("2024-03-01 15:00"),
        )

    assert caught.value.code == "factor_data_source_unavailable"
    assert caught.value.details["skipped_products"] == [{
        "product": "AP.CZC",
        "reason": "no_data_in_formal_window",
    }]
