from __future__ import annotations

import os

import pandas as pd

from tools.data.providers.DataProviderProductTS import DataProviderProductTS
from tools.data.types import DataFreq, DataTime
from tools.data.views.ProductDataView import ProductDataView
from tools.products.Futures import Futures


def test_futures_adjusted_column_selection_returns_only_requested_columns(monkeypatch):
    index = pd.date_range("2024-01-01 09:01", periods=2, freq="1min")
    cached = pd.DataFrame(
        {
            "OPEN": [10.0, 20.0],
            "CLOSE": [11.0, 21.0],
            "VOLUME": [100.0, 200.0],
            "ADJUSTMENT_MUL": [2.0, 2.0],
            "ADJUSTMENT_ADD": [1.0, 1.0],
            "UNUSED": [999.0, 999.0],
        },
        index=index,
    )
    monkeypatch.setattr(ProductDataView, "get_current_source", lambda self: object())
    monkeypatch.setattr(ProductDataView, "_projection_filters", lambda self, **kwargs: ())
    monkeypatch.setattr(ProductDataView, "_load_projected_data", lambda self, **kwargs: cached)
    view = ProductDataView(
        object=Futures("COLUMN_TEST.FUT"),
        data_freq=DataFreq.MIN1,
        alias="COLUMN_TEST_MIN1",
    )

    result = view.get_and_adjust_cols(["CLOSE_ADJUSTED", "VOLUME"], copy=False)

    assert list(result.columns) == ["CLOSE_ADJUSTED", "VOLUME"]
    assert result["CLOSE_ADJUSTED"].tolist() == [23.0, 43.0]
    assert result["VOLUME"].tolist() == [100.0, 200.0]
    assert list(cached.columns) == [
        "OPEN",
        "CLOSE",
        "VOLUME",
        "ADJUSTMENT_MUL",
        "ADJUSTMENT_ADD",
        "UNUSED",
    ]


def test_futures_raw_column_selection_does_not_build_unrequested_adjusted_sibling(monkeypatch):
    cached = pd.DataFrame(
        {
            "CLOSE": [11.0, 21.0],
            "ADJUSTMENT_MUL": [2.0, 2.0],
            "ADJUSTMENT_ADD": [1.0, 1.0],
            "UNUSED": [999.0, 999.0],
        },
        index=pd.date_range("2024-01-01 09:01", periods=2, freq="1min"),
    )
    monkeypatch.setattr(ProductDataView, "get_current_source", lambda self: object())
    monkeypatch.setattr(ProductDataView, "_projection_filters", lambda self, **kwargs: ())
    monkeypatch.setattr(ProductDataView, "_load_projected_data", lambda self, **kwargs: cached)
    view = ProductDataView(
        object=Futures("RAW_COLUMN_TEST.FUT"),
        data_freq=DataFreq.MIN1,
        alias="RAW_COLUMN_TEST_MIN1",
    )

    result = view.get_and_adjust_cols(["CLOSE"], copy=False)

    assert list(result.columns) == ["CLOSE"]
    assert "CLOSE_ADJUSTED" not in cached.columns


def test_parquet_selection_pushes_columns_and_exact_warmup_rows_into_reader(
    monkeypatch,
    request,
    tmp_path,
):
    path = tmp_path / "pushdown.parquet"
    timestamps = pd.date_range("2024-01-02 09:01", periods=10, freq="1min")
    pd.DataFrame(
        {
            "trading_day": timestamps.normalize(),
            "trade_time": timestamps,
            "close_price": range(10, 20),
            "volume": range(100, 110),
            "adjustment_mul": [2.0] * 10,
            "adjustment_add": [1.0] * 10,
            "unused": [999.0] * 10,
        }
    ).to_parquet(path, index=False)

    product = Futures("PUSHDOWN_COLUMNS.FUT")
    source = DataProviderProductTS(
        key="PushdownColumnsMIN1",
        data_freq=DataFreq.MIN1,
        get_object_path=lambda _product: str(path),
        timezone=product.timezone,
        time_cols_mapping={"trade_time": "1min", "trading_day": "1day"},
        data_cols_mapping={
            "close_price": "CLOSE",
            "volume": "VOLUME",
            "adjustment_mul": "ADJUSTMENT_MUL",
            "adjustment_add": "ADJUSTMENT_ADD",
            "unused": "TURNOVER",
        },
    )
    request.addfinalizer(source.delete)
    view = ProductDataView(
        product,
        data_freq=DataFreq.MIN1,
        alias="PUSHDOWN_COLUMNS_MIN1",
        timezone=product.timezone,
    )

    real_read_parquet = pd.read_parquet
    calls = []

    def recording_read_parquet(read_path, *args, **kwargs):
        calls.append({"columns": kwargs.get("columns"), "filters": kwargs.get("filters")})
        return real_read_parquet(read_path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", recording_read_parquet)
    start = DataTime.parse("2024-01-02 09:05", tz=product.timezone)
    end = DataTime.parse("2024-01-02 09:08", tz=product.timezone)

    result = view.get_and_adjust_cols(
        ["CLOSE_ADJUSTED", "VOLUME"],
        copy=False,
        start_dt=start,
        end_dt=end,
        warmup_window=pd.Timedelta(minutes=2),
        source=source,
    )

    assert list(result.columns) == ["CLOSE_ADJUSTED", "VOLUME"]
    assert len(result) == 6
    assert result["CLOSE_ADJUSTED"].tolist() == [25.0, 27.0, 29.0, 31.0, 33.0, 35.0]
    assert len(calls) == 2
    assert set(calls[0]["columns"]) == {"trade_time", "trading_day"}
    projected = calls[1]
    assert set(projected["columns"]) == {
        "trade_time",
        "trading_day",
        "close_price",
        "volume",
        "adjustment_mul",
        "adjustment_add",
    }
    assert "unused" not in projected["columns"]
    assert projected["filters"] == [
        ("trade_time", ">=", pd.Timestamp("2024-01-02 09:03")),
        ("trade_time", "<=", pd.Timestamp("2024-01-02 09:08")),
    ]

    cached = view.get_and_adjust_cols(
        ["CLOSE_ADJUSTED", "VOLUME"],
        copy=False,
        start_dt=start,
        end_dt=end,
        warmup_window=pd.Timedelta(minutes=2),
        source=source,
    )
    assert cached.equals(result)
    assert len(calls) == 2


def test_missing_physical_adjustment_columns_fall_back_to_raw_price(request, tmp_path):
    path = tmp_path / "without-adjustments.parquet"
    timestamps = pd.date_range("2024-01-02 09:01", periods=2, freq="1min")
    pd.DataFrame(
        {
            "trading_day": timestamps.normalize(),
            "trade_time": timestamps,
            "close_price": [11.0, 12.0],
        }
    ).to_parquet(path, index=False)
    product = Futures("NO_PHYSICAL_ADJUSTMENT.FUT")
    source = DataProviderProductTS(
        key="NoPhysicalAdjustmentMIN1",
        data_freq=DataFreq.MIN1,
        get_object_path=lambda _product: str(path),
        timezone=product.timezone,
        time_cols_mapping={"trade_time": "1min", "trading_day": "1day"},
        data_cols_mapping={
            "close_price": "CLOSE",
            "adjustment_mul": "ADJUSTMENT_MUL",
            "adjustment_add": "ADJUSTMENT_ADD",
        },
    )
    request.addfinalizer(source.delete)
    view = ProductDataView(
        product,
        data_freq=DataFreq.MIN1,
        alias="NO_PHYSICAL_ADJUSTMENT_MIN1",
        timezone=product.timezone,
    )

    result = view.get_and_adjust_cols(["CLOSE_ADJUSTED"], copy=False, source=source)

    assert result["CLOSE_ADJUSTED"].tolist() == [11.0, 12.0]


def test_same_source_reads_updated_parquet_for_a_new_calculation(request, tmp_path):
    path = tmp_path / "live-source.parquet"
    timestamps = pd.date_range("2026-10-01 09:01", periods=2, freq="1min")

    def write_prices(values):
        pd.DataFrame({
            "trade_time": timestamps,
            "close_price": values,
        }).to_parquet(path, index=False)

    write_prices([10.0, 11.0])
    product = Futures("LIVE_SOURCE_UPDATE.FUT")
    source = DataProviderProductTS(
        key="LiveUpdatingSourceMIN1",
        data_freq=DataFreq.MIN1,
        get_object_path=lambda _product: str(path),
        timezone=product.timezone,
        time_cols_mapping={"trade_time": "1min"},
        data_cols_mapping={"close_price": "CLOSE"},
    )
    request.addfinalizer(source.delete)
    view = ProductDataView(
        product,
        data_freq=DataFreq.MIN1,
        alias="LIVE_SOURCE_UPDATE_MIN1",
        timezone=product.timezone,
    )

    first_result = view.get_and_adjust_cols(["CLOSE"], copy=False, source=source)
    assert first_result["CLOSE"].tolist() == [10.0, 11.0]

    previous_stat = path.stat()
    write_prices([20.0, 21.0])
    os.utime(
        path,
        ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns + 2_000_000_000),
    )
    second_result = view.get_and_adjust_cols(["CLOSE"], copy=False, source=source)

    assert second_result["CLOSE"].tolist() == [20.0, 21.0]
