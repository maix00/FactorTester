from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd

from tools.testers.backtest.engines.native.ledger import AccountState
from tools.testers.backtest.engines.native.ledger import StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.market_data import (
    MarketDataModule, _causal_valuation, _check_market_data_coverage,
    _load_raw_market_data, current_prices_at, historical_fields_for_product,
)
from tools.data.types.time import DataTime


def test_load_raw_market_data_reads_from_account_supplied_input():
    account = AccountState()
    raw_prices = pd.DataFrame({"P1": [1.0, 2.0]}, index=pd.date_range("2024-01-01", periods=2))
    account.raw_market_data = {"raw_prices": raw_prices, "lot_sizes": {"P1": 5.0}}
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    _load_raw_market_data(account, ctx)
    assert ctx.get(MarketDataModule.raw_prices) is raw_prices
    assert ctx.get(MarketDataModule.lot_sizes) == {"P1": 5.0}


def test_out_of_range_products_emit_one_runtime_info_row(monkeypatch):
    class _Freq:
        name = "min1"

    class _Product:
        def __init__(self, name: str):
            self.name = name
            self.desc = name
            self.min1 = self

        def list_available_freqs(self):
            return [_Freq()]

        def get_and_adjust_cols(self, *args, **kwargs):
            raise ValueError("outside")

    p1 = _Product("ER.CZC")
    p2 = _Product("ME.CZC")
    account = AccountState()
    account.market_data_request = {"products": [p1, p2]}
    setattr(account, "_market_data_load_plan", [(p1, _Freq()), (p2, _Freq())])
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
    account = AccountState()
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

    assert getattr(account, "_market_data_load_plan") == []
    assert getattr(account, "_market_data_excluded_out_of_range") == (product,)
    assert account.runtime_info_rows[0]["details"]["product_names"] == ["FU.SHF@1"]


def test_load_raw_market_data_keeps_all_price_columns_as_price_tables():
    class _Freq:
        name = "min1"

    class _Product:
        name = "P1"
        desc = "P1"

        def __init__(self) -> None:
            self.min1 = self

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
    account = AccountState()
    account.market_data_request = {"products": [product]}
    setattr(account, "_market_data_load_plan", [(product, _Freq())])
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _load_raw_market_data(account, ctx)

    assert set(account.market_price_tables) >= {"open", "high", "low", "close", "vwap"}
    assert account.market_price_tables["open"][product].tolist() == [10.0, 20.0]
    assert account.market_price_tables["high"][product].tolist() == [11.0, 21.0]
    assert account.market_price_tables["low"][product].tolist() == [9.0, 19.0]
    assert account.market_price_tables["close"][product].tolist() == [10.5, 20.5]
    assert account.market_price_tables["vwap"][product].tolist() == [10.25, 20.25]
    assert ctx.get(MarketDataModule.raw_prices)[product].tolist() == [10.5, 20.5]


def test_load_raw_market_data_expands_for_live_strategy_warmup_only():
    class _Freq:
        name = "min1"

    class _Product:
        name = "P1"
        desc = "P1"

        def __init__(self) -> None:
            self.min1 = self
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
    account = AccountState(strategy_configs={
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
    setattr(account, "_market_data_load_plan", [(product, _Freq())])

    _load_raw_market_data(account, FlowContext(timestamp=None, event_queue=EventQueue()))

    assert product.calls[0]["warmup_window"] == pd.Timedelta("2D")


def test_causal_valuation_ffills_gaps_and_never_looks_ahead():
    account = AccountState()
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
