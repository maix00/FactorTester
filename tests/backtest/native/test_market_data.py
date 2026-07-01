from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd
import pytest

from tools.testers.backtest.engines.native.ledger import BacktestRunState
from tools.testers.backtest.engines.native.ledger import StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.market_data import (
    MarketDataModule, _causal_valuation, _check_market_data_coverage,
    _historical_fields_at_from_frames, _load_raw_market_data,
    _resolve_market_data_request, current_prices_at, historical_fields_for_product,
)
from tools.data.types.time import DataTime
from tools.data.types.time_freq import DataFreq
from tools.testers.backtest.modules.product_selection import ProductSelectionModule


def test_load_raw_market_data_reads_from_account_supplied_input():
    account = BacktestRunState()
    raw_prices = pd.DataFrame({"P1": [1.0, 2.0]}, index=pd.date_range("2024-01-01", periods=2))
    account.raw_market_data = {"raw_prices": raw_prices, "lot_sizes": {"P1": 5.0}}
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    _load_raw_market_data(account, ctx)
    assert ctx.get(MarketDataModule.raw_prices) is raw_prices
    assert ctx.get(MarketDataModule.lot_sizes) == {"P1": 5.0}


def test_out_of_range_products_emit_one_runtime_info_row(monkeypatch):
    class _Product:
        def __init__(self, name: str):
            self.name = name
            self.desc = name
            self.MIN1 = self

        def list_available_freqs(self):
            return [DataFreq.MIN1]

        def get_and_adjust_cols(self, *args, **kwargs):
            raise ValueError("outside")

    p1 = _Product("ER.CZC")
    p2 = _Product("ME.CZC")
    account = BacktestRunState()
    account.market_data_request = {"products": [p1, p2]}
    account.market_data_store.load_plan = [(p1, DataFreq.MIN1), (p2, DataFreq.MIN1)]
    account.runtime_info_rows = []
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._product_outside_run_window",
        lambda product, start_dt, end_dt: True,
    )
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _load_raw_market_data(account, ctx)

    assert len(account.runtime_info_rows) == 1
    row = account.runtime_info_rows[0]
    assert row["code"] == "market_data_out_of_range_products_removed"
    assert row["details"]["product_names"] == ["ER.CZC", "ME.CZC"]
    assert "ER.CZC" in row["detail"] and "ME.CZC" in row["detail"]


def test_check_market_data_coverage_excludes_lifecycle_ended_product_without_freqs(monkeypatch):
    class _Product:
        name = "FU.SHF@1"
        desc = "180燃料油"

        def list_available_freqs(self):
            return []

    product = _Product()
    account = BacktestRunState()
    account.market_data_request = {
        "products": [product],
        "start_dt": DataTime.parse("2026-01-01 09:00:00", tz="Asia/Shanghai"),
        "end_dt": DataTime.parse("2026-01-31 15:00:00", tz="Asia/Shanghai"),
    }
    account.runtime_info_rows = []
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._supports_local_cnfutures_coverage",
        lambda item: item is product,
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._product_data_coverage",
        lambda item: None,
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._local_cnfutures_lifecycle_coverage",
        lambda item: (None, pd.Timestamp("2018-06-26")),
    )

    _check_market_data_coverage(account, FlowContext(timestamp=None, event_queue=EventQueue()))

    assert account.market_data_store.load_plan == []
    assert account.market_data_store.excluded_out_of_range == (product,)
    assert account.runtime_info_rows[0]["details"]["product_names"] == ["FU.SHF@1"]


def test_check_market_data_coverage_uses_resolved_frequency_not_first_available():
    class _Product:
        name = "P1"
        current_freq = DataFreq.DAY1

        def list_available_freqs(self):
            return [DataFreq.DAY1, DataFreq.MIN1]

    product = _Product()
    account = BacktestRunState()
    account.market_data_request = {"products": [product]}
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set(MarketDataModule.required_frequency, DataFreq.MIN1)

    _check_market_data_coverage(account, ctx)

    assert account.market_data_store.load_plan == [(product, DataFreq.MIN1, None)]


def test_check_market_data_coverage_rejects_missing_resolved_frequency():
    class _Product:
        name = "P1"

        def list_available_freqs(self):
            return [DataFreq.DAY1]

    account = BacktestRunState()
    account.market_data_request = {"products": [_Product()]}
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set(MarketDataModule.required_frequency, DataFreq.MIN1)

    with pytest.raises(ValueError, match="缺少所需 Bar 频率 MIN1"):
        _check_market_data_coverage(account, ctx)


def test_resolve_market_data_request_records_strategy_frequency_and_source_maps():
    class _Product:
        name = "P1"

        def list_available_freqs(self):
            return [DataFreq.MIN1, DataFreq.DAY1]

    product = _Product()
    s1 = Strategy(alias="S1")
    s2 = Strategy(alias="S2")
    account = BacktestRunState(strategy_configs={
        s1: StrategyConfig(strategy=s1, field_values={
            MarketDataModule.freq_mode: "fixed",
            MarketDataModule.freq_fixed: "MIN1",
        }),
        s2: StrategyConfig(strategy=s2, field_values={
            MarketDataModule.freq_mode: "fixed",
            MarketDataModule.freq_fixed: "DAY1",
        }),
    })
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s1, frozenset({product}))
    ctx.set_for(ProductSelectionModule.products, s2, frozenset({product}))

    _resolve_market_data_request(account, ctx)

    assert ctx.get_for(MarketDataModule.required_frequency, s1) == DataFreq.MIN1
    assert ctx.get_for(MarketDataModule.required_frequency, s2) == DataFreq.DAY1
    assert ctx.get(MarketDataModule.required_frequency) is None
    assert account.market_data_store.required_frequency_by_strategy == {
        s1: DataFreq.MIN1,
        s2: DataFreq.DAY1,
    }

    account = BacktestRunState(strategy_configs={
        s1: StrategyConfig(strategy=s1, field_values={
            MarketDataModule.data_source_mode: "list",
            MarketDataModule.data_source: ["A"],
            MarketDataModule.freq_mode: "fixed",
            MarketDataModule.freq_fixed: "MIN1",
        }),
        s2: StrategyConfig(strategy=s2, field_values={
            MarketDataModule.data_source_mode: "list",
            MarketDataModule.data_source: ["B"],
            MarketDataModule.freq_mode: "fixed",
            MarketDataModule.freq_fixed: "MIN1",
        }),
    })
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s1, frozenset({product}))
    ctx.set_for(ProductSelectionModule.products, s2, frozenset({product}))

    _resolve_market_data_request(account, ctx)

    assert ctx.get_for(MarketDataModule.required_data_source, s1) == ("A",)
    assert ctx.get_for(MarketDataModule.required_data_source, s2) == ("B",)
    assert ctx.get(MarketDataModule.required_data_source) is None
    assert account.market_data_store.required_data_source_by_strategy == {
        s1: ("A",),
        s2: ("B",),
    }


def test_check_market_data_coverage_rejects_same_product_with_conflicting_frequency(monkeypatch):
    class _Product:
        name = "P1"

        def list_available_freqs(self):
            return [DataFreq.MIN1, DataFreq.DAY1]

    product = _Product()
    s1 = Strategy(alias="S1")
    s2 = Strategy(alias="S2")
    account = BacktestRunState(strategy_configs={
        s1: StrategyConfig(strategy=s1),
        s2: StrategyConfig(strategy=s2),
    })
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s1, frozenset({product}))
    ctx.set_for(ProductSelectionModule.products, s2, frozenset({product}))
    ctx.set_for(MarketDataModule.required_frequency, s1, DataFreq.MIN1)
    ctx.set_for(MarketDataModule.required_frequency, s2, DataFreq.DAY1)
    ctx.set_for(MarketDataModule.required_data_source, s1, ())
    ctx.set_for(MarketDataModule.required_data_source, s2, ())
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._select_required_product_source",
        lambda selected_product, freq, required_source: None,
    )

    with pytest.raises(ValueError, match="多个行情请求"):
        _check_market_data_coverage(account, ctx)


def test_check_market_data_coverage_allows_disjoint_products_with_distinct_frequency(monkeypatch):
    class _Product:
        def __init__(self, name: str, freq: DataFreq) -> None:
            self.name = name
            self._freq = freq

        def list_available_freqs(self):
            return [self._freq]

    p1 = _Product("P1", DataFreq.MIN1)
    p2 = _Product("P2", DataFreq.DAY1)
    s1 = Strategy(alias="S1")
    s2 = Strategy(alias="S2")
    account = BacktestRunState(strategy_configs={
        s1: StrategyConfig(strategy=s1),
        s2: StrategyConfig(strategy=s2),
    })
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s1, frozenset({p1}))
    ctx.set_for(ProductSelectionModule.products, s2, frozenset({p2}))
    ctx.set_for(MarketDataModule.required_frequency, s1, DataFreq.MIN1)
    ctx.set_for(MarketDataModule.required_frequency, s2, DataFreq.DAY1)
    ctx.set_for(MarketDataModule.required_data_source, s1, ())
    ctx.set_for(MarketDataModule.required_data_source, s2, ())
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._select_required_product_source",
        lambda selected_product, freq, required_source: None,
    )

    _check_market_data_coverage(account, ctx)

    assert account.market_data_store.load_plan == [
        (p1, DataFreq.MIN1, None),
        (p2, DataFreq.DAY1, None),
    ]


def test_check_market_data_coverage_rejects_missing_required_data_source():
    class _Product:
        name = "P1"

        def list_available_freqs(self):
            return [DataFreq.MIN1]

    account = BacktestRunState()
    account.market_data_request = {"products": [_Product()]}
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set(MarketDataModule.required_frequency, DataFreq.MIN1)
    ctx.set(MarketDataModule.required_data_source, ("MissingSource",))

    with pytest.raises(ValueError, match="缺少所需数据源 MissingSource"):
        _check_market_data_coverage(account, ctx)


def test_check_market_data_coverage_resolves_local_bundle_to_concrete_source(monkeypatch):
    class _Product:
        name = "P1"

        def list_available_freqs(self):
            return [DataFreq.MIN1]

    product = _Product()
    source = object()
    account = BacktestRunState()
    account.market_data_request = {"products": [product]}
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set(MarketDataModule.required_frequency, DataFreq.MIN1)
    ctx.set(MarketDataModule.required_data_source, ("Local",))
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data.DataProviderProductTS.available_for_product",
        lambda selected_product, freq: [source] if selected_product is product and DataFreq(freq) == DataFreq.MIN1 else [],
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._data_sources_for_key_or_bundle",
        lambda key: (type("_Bundle", (), {
            "resolve_for_product": lambda self, selected_product, freq: source
            if selected_product is product and DataFreq(freq) == DataFreq.MIN1 else None,
        })(),) if key == "Local" else (),
    )

    _check_market_data_coverage(account, ctx)

    assert account.market_data_store.load_plan == [(product, DataFreq.MIN1, source)]


def test_data_source_bundle_does_not_pollute_available_frequencies():
    from tools.data.providers.DataProviderProductTSBundle import DataProviderProductTSBundle

    class _Product:
        name = "P1"

    product = _Product()
    bundle = DataProviderProductTSBundle(key="TestBundleNoFreq", members=())

    assert product not in bundle
    assert bundle.freq == DataFreq("0")


def test_load_raw_market_data_keeps_all_price_columns_as_price_tables():
    class _Product:
        name = "P1"
        desc = "P1"

        def __init__(self) -> None:
            self.MIN1 = self

        def get_and_adjust_cols(self, columns, **kwargs):
            idx = pd.date_range("2024-01-01 09:01", periods=2, freq="1min")
            frame = pd.DataFrame({
                "OPEN": [10.0, 20.0],
                "HIGH": [11.0, 21.0],
                "LOW": [9.0, 19.0],
                "CLOSE": [10.5, 20.5],
                "VWAP": [10.25, 20.25],
            }, index=idx)
            return frame[list(columns)]

    product = _Product()
    account = BacktestRunState()
    account.market_data_request = {"products": [product]}
    account.market_data_store.load_plan = [(product, DataFreq.MIN1)]
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _load_raw_market_data(account, ctx)

    assert set(account.market_data_store.market_price_tables) >= {"open", "high", "low", "close", "vwap"}
    assert account.market_data_store.market_price_tables["open"][product].tolist() == [10.0, 20.0]
    assert account.market_data_store.market_price_tables["high"][product].tolist() == [11.0, 21.0]
    assert account.market_data_store.market_price_tables["low"][product].tolist() == [9.0, 19.0]
    assert account.market_data_store.market_price_tables["close"][product].tolist() == [10.5, 20.5]
    assert account.market_data_store.market_price_tables["vwap"][product].tolist() == [10.25, 20.25]
    assert ctx.get(MarketDataModule.raw_prices)[product].tolist() == [10.5, 20.5]


def test_load_raw_market_data_combines_disjoint_products_with_distinct_frequency():
    class _DataView:
        def __init__(self, frame: pd.DataFrame) -> None:
            self.frame = frame
            self.calls: list[dict[str, object]] = []

        def get_and_adjust_cols(self, columns, **kwargs):
            self.calls.append(kwargs)
            return self.frame[list(columns)]

    class _Product:
        def __init__(self, name: str, freq: DataFreq, frame: pd.DataFrame) -> None:
            self.name = name
            self.desc = name
            setattr(self, freq.name, _DataView(frame))

    price_columns = {
        "OPEN": [10.0, 20.0],
        "HIGH": [11.0, 21.0],
        "LOW": [9.0, 19.0],
        "CLOSE": [10.5, 20.5],
        "VWAP": [10.25, 20.25],
    }
    min1_frame = pd.DataFrame(
        price_columns,
        index=pd.date_range("2024-01-01 09:01", periods=2, freq="1min"),
    )
    day1_frame = pd.DataFrame(
        {
            "OPEN": [100.0],
            "HIGH": [110.0],
            "LOW": [90.0],
            "CLOSE": [105.0],
            "VWAP": [102.5],
        },
        index=pd.DatetimeIndex([pd.Timestamp("2024-01-01 15:00")]),
    )
    p1 = _Product("P1", DataFreq.MIN1, min1_frame)
    p2 = _Product("P2", DataFreq.DAY1, day1_frame)
    account = BacktestRunState()
    account.market_data_store.load_plan = [
        (p1, DataFreq.MIN1, None),
        (p2, DataFreq.DAY1, None),
    ]
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _load_raw_market_data(account, ctx)

    raw_prices = ctx.get(MarketDataModule.raw_prices)
    assert list(raw_prices.columns) == [p1, p2]
    assert raw_prices[p1].dropna().tolist() == [10.5, 20.5]
    assert raw_prices[p2].dropna().tolist() == [105.0]
    assert account.market_data_store.market_price_tables["open"][p1].dropna().tolist() == [10.0, 20.0]
    assert account.market_data_store.market_price_tables["open"][p2].dropna().tolist() == [100.0]


def test_load_raw_market_data_expands_for_live_strategy_warmup_only():
    class _Product:
        name = "P1"
        desc = "P1"

        def __init__(self) -> None:
            self.MIN1 = self
            self.calls = []

        def get_and_adjust_cols(self, columns, **kwargs):
            self.calls.append(kwargs)
            idx = pd.date_range("2024-01-01 09:01", periods=2, freq="1min")
            return pd.DataFrame({
                "OPEN": [10.0, 20.0],
                "HIGH": [11.0, 21.0],
                "LOW": [9.0, 19.0],
                "CLOSE": [10.5, 20.5],
                "VWAP": [10.25, 20.25],
            }, index=idx)[list(columns)]

    live = Strategy(alias="live")
    precomputed = Strategy(alias="pre")
    product = _Product()
    account = BacktestRunState(strategy_configs={
        live: StrategyConfig(
            strategy=live,
            active_flow_names=frozenset({"signal_live"}),
            field_values={
                FactorModule.factor: object(),
                FactorSignalModule.warmup_mode: "fixed",
                FactorSignalModule.warmup_window: "2d",
            },
        ),
        precomputed: StrategyConfig(
            strategy=precomputed,
            active_flow_names=frozenset({"signal_precomputed"}),
            field_values={
                FactorModule.factor: object(),
                FactorSignalModule.warmup_mode: "fixed",
                FactorSignalModule.warmup_window: "30d",
            },
        ),
    })
    account.market_data_request = {"products": [product]}
    account.market_data_store.load_plan = [(product, DataFreq.MIN1)]

    _load_raw_market_data(account, FlowContext(timestamp=None, event_queue=EventQueue()))

    assert product.calls[0]["warmup_window"] == pd.Timedelta("2D")


def test_causal_valuation_ffills_gaps_and_never_looks_ahead():
    account = BacktestRunState()
    idx = pd.date_range("2024-01-01", periods=4)
    raw_prices = pd.DataFrame({"P1": [10.0, np.nan, np.nan, 40.0]}, index=idx)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set(MarketDataModule.raw_prices, raw_prices)
    _causal_valuation(account, ctx)

    # gap at idx[1]/idx[2] should be filled with the prior observed value (10.0),
    # not the future value (40.0) -- this is the no-lookahead guarantee
    assert current_prices_at(account, cast(pd.Timestamp, idx[1]))["P1"] == 10.0
    assert current_prices_at(account, cast(pd.Timestamp, idx[2]))["P1"] == 10.0
    assert current_prices_at(account, cast(pd.Timestamp, idx[3]))["P1"] == 40.0
    assert current_prices_at(account, cast(pd.Timestamp, idx[0]))["P1"] == 10.0


def test_historical_fields_for_product_matches_product_and_string_keys():
    class _Product:
        name = "RU.SHF"
        alias = "RU.SHF"
        code = "RU"

        def __str__(self) -> str:
            return self.name

    product = _Product()
    fields: dict[str, object] = {"VolumeMultiple": 10.0}

    assert historical_fields_for_product({"RU.SHF": fields}, product) is fields
    assert historical_fields_for_product({product: fields}, "RU.SHF") is fields


def test_historical_fields_at_uses_asof_for_causal_order_timestamp():
    frame_ts = pd.Timestamp("2026-01-05 09:01:00")
    event_ts = cast(pd.Timestamp, pd.Timestamp("2026-01-05 09:01:00.000000001", tz="Asia/Shanghai"))
    frames = {
        "OpenRatioByMoney": pd.DataFrame({"EG.DCE": [0.0001]}, index=pd.DatetimeIndex([frame_ts])),
        "VolumeMultiple": pd.DataFrame({"EG.DCE": [10]}, index=pd.DatetimeIndex([frame_ts])),
    }

    fields = _historical_fields_at_from_frames(frames, ["EG.DCE"], event_ts)

    assert fields["EG.DCE"]["OpenRatioByMoney"] == 0.0001
    assert fields["EG.DCE"]["VolumeMultiple"] == 10


def test_historical_fields_at_does_not_look_ahead_before_first_row():
    frame_ts = pd.Timestamp("2026-01-05 09:01:00")
    event_ts = cast(pd.Timestamp, pd.Timestamp("2026-01-05 09:00:59.999999999", tz="Asia/Shanghai"))
    frames = {
        "OpenRatioByMoney": pd.DataFrame({"EG.DCE": [0.0001]}, index=pd.DatetimeIndex([frame_ts])),
    }

    fields = _historical_fields_at_from_frames(frames, ["EG.DCE"], event_ts)

    assert fields["EG.DCE"] == {}
