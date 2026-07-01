import pandas as pd
import pytest

from tools.data.types import DataIndex, DataTime


def test_exact_slice_allows_daily_spaced_intraday_timestamps():
    index = pd.Index(pd.to_datetime([
        "2025-01-01 09:00",
        "2025-01-02 09:00",
        "2025-01-03 09:00",
    ]))

    mask = DataIndex(index).slice_by_datatime(
        DataTime.parse("2025-01-02 09:00", precision="exact"),
        DataTime.parse("2025-01-02 09:00", precision="exact"),
    )

    assert mask.tolist() == [False, True, False]


def test_exact_slice_rejects_midnight_only_daily_index():
    index = pd.Index(pd.to_datetime([
        "2025-01-01",
        "2025-01-02",
        "2025-01-03",
    ]))

    with pytest.raises(ValueError, match="exact precision requires intraday"):
        DataIndex(index).slice_by_datatime(
            DataTime.parse("2025-01-02 09:00", precision="exact"),
            DataTime.parse("2025-01-02 09:00", precision="exact"),
        )


def test_datatime_sort_key_normalizes_timezone_for_ordering():
    shanghai = DataTime.parse("2025-01-02 09:00", precision="exact", tz="Asia/Shanghai")
    utc = DataTime.parse("2025-01-02 01:00", precision="exact", tz="UTC")

    assert shanghai.sort_key() == utc.sort_key()
