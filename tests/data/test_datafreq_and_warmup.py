from __future__ import annotations

import pandas as pd

from tools.data.types import DataFreq, DataTime
from tools.data.views.ProductDataView import ProductDataView


def test_datafreq_addition_normalizes_result() -> None:
    assert DataFreq("1D") + DataFreq("30min") == DataFreq("1D30min")
    assert sum([DataFreq("15min"), DataFreq("45min")]) == DataFreq("1h")


def test_product_data_view_warmup_expands_left_by_real_bars() -> None:
    class _Product:
        alias = "Product:WARMUP"
        name = "WARMUP"

    product = _Product()
    view = ProductDataView(product, data_freq=DataFreq.MIN1)
    setattr(product, "MIN1", view)

    trade_times = pd.DatetimeIndex(
        [
            "2024-01-01 14:59",
            "2024-01-01 15:00",
            "2024-01-02 09:01",
            "2024-01-02 09:02",
        ],
        tz="Asia/Shanghai",
        name="MIN1",
    )
    index = pd.MultiIndex.from_arrays(
        [pd.DatetimeIndex([ts.normalize().tz_localize(None) for ts in trade_times]), trade_times],
        names=["DAY1", "MIN1"],
    )
    data = pd.DataFrame({"CLOSE": [1.0, 2.0, 3.0, 4.0]}, index=index)
    start = DataTime.from_dict(
        {"date": "2024-01-02", "time": "09:01", "tz": "Asia/Shanghai"},
        precision="exact",
    )
    end = DataTime.from_dict(
        {"date": "2024-01-02", "time": "09:02", "tz": "Asia/Shanghai"},
        precision="exact",
    )

    result = view._filter_data_by_calc_window(data, start=start, end=end, warmup_window="2min")

    assert list(result["CLOSE"]) == [1.0, 2.0, 3.0, 4.0]
