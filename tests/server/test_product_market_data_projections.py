from __future__ import annotations

import pandas as pd
import pytest
from types import SimpleNamespace

from server.modules.shared.price_data_helpers import open_interest_column
from server.services.product_market_data.errors import ProductMarketDataError
from server.services.product_market_data.products import _price_rows
from server.services.product_market_data import products as product_projection
from server.services.product_market_data.ranges import latest_relative_start
from server.services.product_market_data.sampling import (
    bounded_ohlcv_frame, bounded_ohlcv_rows, fixed_chart_frame,
)
from tools.data.types import DataFreq


def test_contract_frequency_column_uses_registered_sources(monkeypatch) -> None:
    from server.services.product_market_data import contracts as projection

    monkeypatch.setattr(projection, "cached_products", lambda: (object(),))
    monkeypatch.setattr(projection, "find_product", lambda products, name: products[0])
    monkeypatch.setattr(projection, "supports_term_structure", lambda product: True)
    monkeypatch.setattr(projection, "get_product_contracts", lambda product, **kwargs: [
        {"uid": "both"}, {"uid": "daily"}, {"uid": "absent"},
        {"uid": "stream"},
    ])
    monkeypatch.setattr(projection, "contract_available_sources", lambda uid: {
        "both": [{"alias": "minute", "freq": "MIN1"},
                 {"alias": "daily", "freq": "DAY1"}],
        "daily": [{"alias": "daily", "freq": "DAY1"}], "absent": [],
        "stream": [{"alias": "live-level2", "freq": "TICK",
                    "delivery_mode": "live_stream"}],
    }[uid])
    monkeypatch.setattr(projection, "product_public_fields", lambda product: {})

    rows = projection.contract_listing("sample")["contracts"]
    assert [(row["available_freqs"], row["has_data"]) for row in rows] == [
        (["MIN1", "DAY1"], True), (["DAY1"], True), ([], False),
        (["TICK"], True),
    ]
    assert [source["alias"] for source in rows[0]["available_sources"]] == [
        "minute", "daily",
    ]


def test_day_only_contract_uses_term_snapshot_source(tmp_path, monkeypatch) -> None:
    from server.services.product_market_data import contracts as projection
    from sources.LocalCNFutures import CNFutures as source_module

    uid = "DCE|F|FB|2402"
    path = tmp_path / "term.parquet"
    pd.DataFrame({
        "CONTRACT_UID": [uid, "another"],
        "TRADING_DAY": pd.to_datetime(["2024-01-04", "2024-01-04"]),
        "OPEN": [10., 20.], "HIGH": [12., 22.],
        "LOW": [9., 19.], "CLOSE": [11., 21.],
        "VOLUME": [100., 200.], "OPEN_INTEREST": [50., 60.],
    }).to_parquet(path)
    assert source_module.term_contract_has_day_data(uid, str(path))
    assert not source_module.term_contract_has_day_data("missing", str(path))
    monkeypatch.setattr(projection, "find_contract_product", lambda value: SimpleNamespace(
        timezone="Asia/Shanghai",
    ))
    monkeypatch.setattr(projection, "contract_available_freqs", lambda value: ["DAY1"])
    monkeypatch.setattr(projection, "available_sources_for_product", lambda value: [
        {"alias": "LocalCNFuturesContractDAY1", "freq": "DAY1"},
    ])
    monkeypatch.setattr(projection, "DataSource", {
        "LocalCNFuturesContractDAY1": SimpleNamespace(
            contract_data_layout="term_structure_snapshot",
            get_path=lambda product: str(path),
        ),
    })
    monkeypatch.setattr(projection, "product_public_fields", lambda value: {})

    result = projection.contract_price_series({
        "contract_uid": uid, "chart_mode": "fixed", "chart_interval": "DAY1",
    })
    assert result["freq"] == "DAY1"
    assert result["data_source"] == "LocalCNFuturesContractDAY1"
    assert result["count"] == 1
    assert result["data"][0]["open"] == 10.
    assert result["data"][0]["open_interest"] == 50.


def test_open_interest_column_accepts_canonical_and_provider_aliases() -> None:
    assert open_interest_column(["OPEN", "OPEN_INTEREST", "CLOSE"]) == "OPEN_INTEREST"
    assert open_interest_column(["open_price", "open_interest", "close_price"]) == "open_interest"
    assert open_interest_column(["open", "OI", "close"]) == "OI"
    assert open_interest_column(["open", "hold", "close"]) == "hold"
    assert open_interest_column(["open", "close"]) is None


def test_product_price_rows_keeps_open_interest_from_provider_alias() -> None:
    frame = pd.DataFrame(
        {
            "OPEN": [10.0, 11.0],
            "HIGH": [12.0, 13.0],
            "LOW": [9.0, 10.0],
            "CLOSE": [11.0, 12.0],
            "VOLUME": [100, 120],
            "OI": [80, 90],
        },
        index=pd.date_range("2025-01-02", periods=2, freq="D"),
    )

    rows, has_open_interest = _price_rows(
        object(), frame, adjusted=False, frequency=DataFreq.DAY1,
    )

    assert has_open_interest is True
    assert [row["open_interest"] for row in rows] == [80.0, 90.0]


def test_product_chart_sampling_preserves_ohlcv_bucket_semantics() -> None:
    rows = [{
        "timestamp": index, "open": index + 1, "high": index + 3,
        "low": index, "close": index + 2, "volume": 10,
        "open_interest": 100 + index,
    } for index in range(200)]

    sampled, total = bounded_ohlcv_rows(rows, {"max_points": 100})

    assert total == 200
    assert len(sampled) == 100
    assert sampled[0] == {
        **rows[1], "timestamp": 1, "time": None,
        "open": 1, "high": 4, "low": 0,
        "close": 3, "volume": 20, "open_interest": 101,
    }


def test_frame_aggregation_matches_serialized_ohlcv_buckets() -> None:
    count = 203
    frame = pd.DataFrame({
        "OPEN": [float(i) for i in range(count)],
        "HIGH": [float(i + 2) for i in range(count)],
        "LOW": [float(i - 3) for i in range(count)],
        "CLOSE": [float(i + 1) for i in range(count)],
        "VOLUME": [float(i % 7) for i in range(count)],
        "OPEN_INTEREST": [float(500 + i) for i in range(count)],
    }, index=pd.date_range("2025-01-01", periods=count, freq="min"))
    columns = ("OPEN", "HIGH", "LOW", "CLOSE", "VOLUME")
    sampled_frame, raw_count = bounded_ohlcv_frame(
        frame, {"max_points": 100}, columns, "OPEN_INTEREST",
    )
    sampled_rows, _ = _price_rows(
        object(), sampled_frame, adjusted=False, frequency=DataFreq.MIN1,
    )
    raw_rows, _ = _price_rows(
        object(), frame, adjusted=False, frequency=DataFreq.MIN1,
    )
    expected, _ = bounded_ohlcv_rows(raw_rows, {"max_points": 100})
    assert raw_count == count
    assert sampled_rows == expected


def test_fixed_chart_aggregation_respects_selected_interval_and_source_rows() -> None:
    frame = pd.DataFrame({
        "open": [10, 11, 12, 13], "high": [12, 13, 14, 15],
        "low": [9, 10, 11, 12], "close": [11, 12, 13, 14],
        "volume": [1, 2, 3, 4], "oi": [100, 101, 102, 103],
    }, index=pd.date_range("2025-01-01 09:01", periods=4, freq="min"))
    columns = ("open", "high", "low", "close", "volume")
    raw, count = fixed_chart_frame(frame, {"chart_interval": "SOURCE",
                                           "max_points": 100}, columns, DataFreq.MIN1, "oi")
    assert count == 4 and raw.equals(frame)
    grouped, count = fixed_chart_frame(frame, {"chart_interval": "MIN5",
                                               "max_points": 100}, columns, DataFreq.MIN1, "oi")
    assert count == 1
    assert grouped.index[0] == pd.Timestamp("2025-01-01 09:05")
    assert grouped.iloc[0][["open", "high", "low", "close", "volume", "oi"]].tolist() \
        == [10, 15, 9, 14, 10, 103]


@pytest.mark.parametrize("interval,minute", [
    ("MIN5", 5), ("MIN15", 15), ("MIN30", 30), ("HOUR1", 60),
])
def test_fixed_chart_intraday_bars_use_right_closed_end_labels(interval, minute) -> None:
    boundary = pd.Timestamp("2025-01-02 09:00") + pd.Timedelta(minutes=minute)
    stamps = pd.DatetimeIndex([
        pd.Timestamp("2025-01-02 09:01"), boundary,
        boundary + pd.Timedelta(minutes=1),
    ])
    frame = pd.DataFrame({
        "open": [10, 11, 12], "high": [12, 13, 14],
        "low": [9, 8, 7], "close": [11, 12, 13],
        "volume": [2, 3, 5], "oi": [100, 101, 102],
    }, index=stamps)
    columns = ("open", "high", "low", "close", "volume")
    result, count = fixed_chart_frame(
        frame, {"chart_interval": interval}, columns, DataFreq.MIN1, "oi")
    assert count == 2
    assert list(result.index) == [boundary, boundary + pd.Timedelta(minutes=minute)]
    assert result.iloc[0][list(columns) + ["oi"]].tolist() == [10, 13, 8, 12, 5, 101]
    assert result.iloc[1][list(columns) + ["oi"]].tolist() == [12, 14, 7, 13, 5, 102]


def test_fixed_chart_contract_time_column_uses_bucket_end() -> None:
    frame = pd.DataFrame({
        "trade_time": pd.to_datetime(["2025-01-02 09:01", "2025-01-02 09:05"]),
        "open": [1, 2], "high": [2, 3], "low": [0, 1],
        "close": [2, 3], "volume": [4, 5],
    })
    result, count = fixed_chart_frame(
        frame, {"chart_interval": "MIN5"},
        ("open", "high", "low", "close", "volume"), DataFreq.MIN1,
        time_column="trade_time")
    assert count == 1
    assert result.iloc[0]["trade_time"] == pd.Timestamp("2025-01-02 09:05")
    assert result.iloc[0]["volume"] == 9


def test_fixed_chart_rejects_oversized_selection_instead_of_changing_frequency() -> None:
    frame = pd.DataFrame({"open": range(200), "high": range(200),
                          "low": range(200), "close": range(200),
                          "volume": [1] * 200},
                         index=pd.date_range("2025-01-01", periods=200, freq="min"))
    with pytest.raises(ProductMarketDataError, match="更粗的频率或更短的范围"):
        fixed_chart_frame(frame, {"chart_interval": "SOURCE", "max_points": 100},
                          ("open", "high", "low", "close", "volume"), DataFreq.MIN1)


def test_recent_chart_ranges_follow_last_source_bar_not_wall_clock() -> None:
    index = pd.date_range("2010-01-04", "2025-05-25", freq="D", tz="Asia/Shanghai")
    last = index[-1]
    assert latest_relative_start(index, "day") == last - pd.DateOffset(days=1)
    assert latest_relative_start(index, "month") == last - pd.DateOffset(months=1)
    assert latest_relative_start(index, "year") == last - pd.DateOffset(years=1)
    assert latest_relative_start(index, "ytd") == pd.Timestamp(
        "2025-01-01", tz="Asia/Shanghai")
    with pytest.raises(ValueError, match="Unsupported chart range"):
        latest_relative_start(index, "unknown")


def test_live_chart_interval_requires_declared_live_source() -> None:
    frame = pd.DataFrame({"open": [1], "high": [2], "low": [1],
                          "close": [2], "volume": [1]},
                         index=pd.date_range("2025-01-01", periods=1, freq="min"))
    columns = ("open", "high", "low", "close", "volume")
    with pytest.raises(ProductMarketDataError, match="不提供实时"):
        fixed_chart_frame(frame, {"chart_interval": "LIVE"}, columns, DataFreq.MIN1)
    result, count = fixed_chart_frame(
        frame, {"chart_interval": "LIVE"}, columns, DataFreq.MIN1,
        source_delivery_mode="live_stream")
    assert count == 1 and result.equals(frame)


def test_daily_full_history_fits_explicit_chart_budget() -> None:
    dates = pd.bdate_range("2010-01-04", periods=3980)
    frame = pd.DataFrame({"open": 1, "high": 2, "low": 1,
                          "close": 2, "volume": 1}, index=dates)
    result, count = fixed_chart_frame(
        frame, {"chart_interval": "DAY1", "max_points": 5000},
        ("open", "high", "low", "close", "volume"), DataFreq.DAY1)
    assert count == 3980 and result.index[0] == dates[0]


def test_product_recent_range_uses_source_coverage(monkeypatch) -> None:
    dates = pd.bdate_range("2020-01-01", "2025-05-23")
    frame = pd.DataFrame({"OPEN": 1.0, "HIGH": 2.0, "LOW": 1.0,
                          "CLOSE": 2.0, "VOLUME": 1.0}, index=dates)
    source = SimpleNamespace(key="HistoricalTestDAY1",
                             delivery_mode="historical_snapshot")

    class DataMeta:
        current_source = source

        def get_current_source(self):
            return source

    class Product:
        name = "TEST.LOCAL"
        timezone = "Asia/Shanghai"
        current_freq = DataFreq.DAY1
        DAY1 = DataMeta()

        def get_series_variants(self):
            return [SimpleNamespace(variant="primary_raw", adjusted=False,
                                    backing_product_name=self.name)]

        def set_current_freq(self, frequency):
            self.current_freq = frequency

        def get_some_data(self, _frequency, copy=False):
            return frame

        def get_price_data(self, start, end, adjusted=False):
            return frame.loc[(frame.index >= start) & (frame.index <= end)].copy()

    product = Product()
    monkeypatch.setattr(product_projection, "cached_products", lambda: [product])
    monkeypatch.setattr(product_projection, "find_product", lambda _, __: product)
    monkeypatch.setattr(product_projection, "product_public_fields", lambda _: {})
    monkeypatch.setattr(product_projection, "supports_term_structure", lambda _: False)
    monkeypatch.setattr(product_projection, "supports_adjusted_price", lambda _: False)
    monkeypatch.setattr(product_projection, "available_sources_for_product",
                        lambda _: [])
    monkeypatch.setattr(product_projection, "available_freq_names_for_product",
                        lambda _: ["DAY1"])
    result = product_projection.product_price_series({
        "product_name": "TEST.LOCAL", "chart_mode": "fixed",
        "chart_interval": "DAY1", "chart_range": "year", "max_points": 5000,
    })
    assert result["count"] < len(frame)
    assert result["data"][0]["timestamp"] >= pd.Timestamp(
        "2024-05-23", tz="Asia/Shanghai").timestamp() * 1000
    assert result["data"][-1]["timestamp"] == pd.Timestamp(
        "2025-05-23", tz="Asia/Shanghai").timestamp() * 1000


def test_fixed_chart_rejects_interval_finer_than_source() -> None:
    frame = pd.DataFrame({"open": [1], "high": [1], "low": [1],
                          "close": [1], "volume": [1]},
                         index=pd.date_range("2025-01-01", periods=1, freq="D"))
    with pytest.raises(ProductMarketDataError, match="不能细于数据源"):
        fixed_chart_frame(frame, {"chart_interval": "MIN5"},
                          ("open", "high", "low", "close", "volume"),
                          DataFreq.DAY1)


def test_fixed_chart_weekly_aggregation_works_with_daily_source() -> None:
    frame = pd.DataFrame({"open": [1, 2, 3], "high": [2, 3, 4],
                          "low": [1, 2, 3], "close": [2, 3, 4],
                          "volume": [1, 2, 3]},
                         index=pd.to_datetime(["2025-01-03", "2025-01-06", "2025-01-07"]))
    result, count = fixed_chart_frame(frame, {"chart_interval": "WEEK1"},
                                      ("open", "high", "low", "close", "volume"),
                                      DataFreq.DAY1)
    assert count == 2
    assert list(result.index) == [pd.Timestamp("2025-01-05"),
                                  pd.Timestamp("2025-01-12")]
    assert result.iloc[0]["volume"] == 1
    assert result.iloc[1]["volume"] == 5


def test_fixed_chart_daily_bucket_uses_contract_trading_day() -> None:
    frame = pd.DataFrame({
        "trade_time": pd.to_datetime(["2025-01-01 21:00", "2025-01-02 09:00"]),
        "trading_day": pd.to_datetime(["2025-01-02", "2025-01-02"]),
        "open": [10, 11], "high": [12, 13], "low": [9, 10],
        "close": [11, 12], "volume": [1, 2],
    })
    result, count = fixed_chart_frame(frame, {"chart_interval": "DAY1",
                                               "max_points": 100},
                                      ("open", "high", "low", "close", "volume"),
                                      DataFreq.MIN1, time_column="trade_time",
                                      trading_day_column="trading_day")
    assert count == 1
    assert result.iloc[0]["trade_time"] == pd.Timestamp("2025-01-02")
    assert result.iloc[0]["volume"] == 3


def test_fixed_chart_daily_bucket_uses_product_trading_day_index() -> None:
    index = pd.MultiIndex.from_arrays([
        pd.to_datetime(["2025-01-02", "2025-01-02"]),
        pd.to_datetime(["2025-01-01 21:00", "2025-01-02 09:00"]),
    ], names=["trading_day", "_SIGNAL@MIN1"])
    frame = pd.DataFrame({"open": [10, 11], "high": [12, 13],
                          "low": [9, 10], "close": [11, 12],
                          "volume": [1, 2]}, index=index)
    result, count = fixed_chart_frame(frame, {"chart_interval": "DAY1",
                                               "max_points": 100},
                                      ("open", "high", "low", "close", "volume"),
                                      DataFreq.MIN1)
    assert count == 1
    assert result.iloc[0]["volume"] == 3
    assert result.index[0] == pd.Timestamp("2025-01-02")


def test_frame_aggregation_leaves_anchored_bars_for_exact_row_sampling() -> None:
    frame = pd.DataFrame({"OPEN": range(200), "HIGH": range(200),
                          "LOW": range(200), "CLOSE": range(200),
                          "VOLUME": range(200)},
                         index=pd.date_range("2025-01-01", periods=200, freq="min"))
    sampled, count = bounded_ohlcv_frame(frame, {
        "max_points": 100, "anchor_timestamps": [1735689600000],
    }, ("OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"))
    assert count == 200
    assert sampled is frame


def test_contract_frame_aggregation_preserves_time_and_restores_source_bars() -> None:
    frame = pd.DataFrame({
        "trade_time": pd.date_range("2025-01-01", periods=210, freq="min"),
        "open_price": range(210), "highest_price": range(210),
        "lowest_price": range(210), "close_price": range(210),
        "volume": [1] * 210, "open_interest": range(210),
    })
    columns = ("open_price", "highest_price", "lowest_price", "close_price", "volume")
    overview, total = bounded_ohlcv_frame(
        frame, {"max_points": 100}, columns, "open_interest",
        time_column="trade_time",
    )
    assert total == 210
    assert len(overview) == 70
    assert overview.iloc[0]["trade_time"] == frame.iloc[2]["trade_time"]
    assert overview.iloc[0]["open_interest"] == 2
    assert overview.iloc[0]["volume"] == 3
    detail, total = bounded_ohlcv_frame(
        frame.iloc[25:40], {"max_points": 100}, columns, "open_interest",
        time_column="trade_time",
    )
    assert total == 15
    assert detail.equals(frame.iloc[25:40])


def test_product_chart_sampling_keeps_event_candle_and_neighbors_aggregated() -> None:
    rows = [{
        "timestamp": index * 60_000, "open": index + 1,
        "high": index + 3, "low": index, "close": index + 2,
        "volume": 10, "open_interest": 100 + index,
    } for index in range(300)]
    sampled, total = bounded_ohlcv_rows(rows, {
        "max_points": 100,
        "anchor_timestamps": [101 * 60_000 + 15_000, 102 * 60_000],
        "anchor_tolerance_ms": 60_000,
    })
    assert total == 300
    assert rows[101] in sampled and rows[102] in sampled
    assert sampled[0]["volume"] == 30
    assert len(sampled) <= 104
    assert [row["timestamp"] for row in sampled] == sorted(
        row["timestamp"] for row in sampled
    )


def test_product_chart_sampling_does_not_pin_distant_event() -> None:
    rows = [{"timestamp": index * 60_000, "open": index, "high": index + 1,
             "low": index - 1, "close": index, "volume": 1}
            for index in range(200)]
    sampled, _ = bounded_ohlcv_rows(rows, {"max_points": 100,
        "anchor_timestamps": [100 * 60_000 + 30_000],
        "anchor_tolerance_ms": 1_000})
    assert len(sampled) == 100


def test_manager_product_fields_resolves_contracts_for_independent_detail_tabs(
    monkeypatch,
) -> None:
    from server.manager.services.client_state import ClientStateService
    from server.modules.shared import price_services
    from server.services import product_catalog_projection

    class Parent:
        name = "A.DCE"

    class Contract:
        name = "DCE|A|2501"
        parent_product = Parent()

    monkeypatch.setattr(price_services, "cached_products", lambda: ())
    monkeypatch.setattr(
        price_services, "find_contract_product", lambda value: Contract(),
    )
    monkeypatch.setattr(
        price_services, "find_product", lambda products, value: None,
    )
    monkeypatch.setattr(
        price_services, "product_public_fields",
        lambda value: {"contract_uid": {"value": value.name}},
    )
    monkeypatch.setattr(
        product_catalog_projection,
        "catalog_product_records",
        lambda: ({
            "name": "A.DCE",
            "source_ids": ["PublicSource"],
            "available_source_ids": ["PublicSource"],
        },),
    )
    monkeypatch.setattr(
        product_catalog_projection,
        "catalog_product_description",
        lambda product, name: "A产品",
    )

    value = ClientStateService.product_fields("DCE|A|2501")

    assert value["product_type"] == "contract"
    assert value["name"] == "DCE|A|2501"
    assert value["parent_product"] == "A.DCE"
    assert value["source_ids"] == ["PublicSource"]
    assert value["fields"]["contract_uid"]["value"] == "DCE|A|2501"
