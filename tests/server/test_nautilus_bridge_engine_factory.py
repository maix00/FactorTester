"""Engine construction keeps Venue accounts native and market data shared."""

from __future__ import annotations

import sys
from decimal import Decimal
from types import ModuleType, SimpleNamespace

import pytest

from server.services.nautilus_bridge.config import (
    UnsupportedExecutionConfig,
    compile_frozen_execution_plan,
    freeze_instrument_execution_policy,
)
from server.services.nautilus_bridge.engine_factory import add_data_batch, build_backtest_engine


def _plan():
    return compile_frozen_execution_plan({
        "data_source_ref": "LocalCNFuturesMIN1@revision-1",
        "source_version": "sha256:source", "product_scope_refs": ["scope:x"],
        "start_utc": "2025-04-01T01:00:00Z", "end_utc": "2025-04-02T07:00:00Z",
        "bar_end_timestamps": True, "execution_price_basis": "open",
        "execution_timing": "next_bar_open", "fee_mode": "zero",
        "initial_capital_major": "1000000", "base_currency": "CNY",
        "account_model": "one_account_per_venue",
        "execution_model": "one_backtest_engine_per_run", "shared_market_data": True,
        "venues": [
            {"name": "CFFEX", "account_type": "MARGIN", "oms_type": "NETTING",
             "starting_balances": ["600000 CNY"], "base_currency": "CNY"},
            {"name": "SHFE", "account_type": "MARGIN", "oms_type": "HEDGING",
             "starting_balances": ["400000 CNY"], "base_currency": "CNY"},
        ],
        "strategy_venue_bindings": [
            {"strategy_id": "strategy:a", "venue_ids": ["CFFEX"],
             "product_scope_refs": ["scope:x"]},
            {"strategy_id": "strategy:b", "venue_ids": ["SHFE"],
             "product_scope_refs": ["scope:x"]},
        ],
        "instrument_execution_policy": freeze_instrument_execution_policy(
            preset="basic",
        ).manifest(),
    }, feed_kind="bar", adapter_capabilities=frozenset({"native_bar_open_market_orders"}))


class _InstrumentId:
    def __init__(self, text: str):
        self.text = text
        self.venue = text.rsplit(".", 1)[-1]

    def __str__(self):
        return self.text

    @classmethod
    def from_str(cls, text: str):
        return cls(text)


class _FuturesContract:
    def __init__(self, text: str):
        self.id = _InstrumentId(text)


class _FakeEngine:
    instances = []

    def __init__(self, config):
        self.config = config
        self.venues = []
        self.instruments = []
        self.batches = []
        self.disposed = False
        self.instances.append(self)

    def add_venue(self, **kwargs):
        self.venues.append(kwargs)

    def add_instrument(self, instrument):
        self.instruments.append(instrument)

    def add_data_batch(self, batch, **kwargs):
        self.batches.append((batch, kwargs))

    def dispose(self):
        self.disposed = True


def _install_nautilus_fakes(monkeypatch):
    root = ModuleType("nautilus_trader")
    root.__path__ = []
    backtest = ModuleType("nautilus_trader.backtest")
    backtest.BacktestEngine = _FakeEngine
    config = ModuleType("nautilus_trader.config")
    config.BacktestEngineConfig = lambda **kwargs: kwargs
    execution = ModuleType("nautilus_trader.execution")
    execution.ExecutionEngineConfig = lambda **kwargs: kwargs
    execution_names = (
        "BestPriceFillModel", "CappedOptionFeeModel", "CompetitionAwareFillModel",
        "DefaultFillModel", "FixedFeeModel", "LimitOrderPartialFillModel",
        "MakerTakerFeeModel", "MarketHoursFillModel", "OneTickSlippageFillModel",
        "PerContractFeeModel", "ProbabilisticFillModel", "ProbabilityPriceFeeModel",
        "SizeAwareFillModel", "StaticLatencyModel", "ThreeTierFillModel",
        "TieredNotionalOptionFeeModel", "TwoTierFillModel", "VolumeSensitiveFillModel",
    )
    for name in execution_names:
        setattr(execution, name, lambda *args, _name=name, **kwargs: (_name, args, kwargs))

    class _Value:
        @classmethod
        def from_str(cls, value):
            return value

    class _Money:
        def __init__(self, amount, currency):
            self.amount = Decimal(amount)
            self.currency = currency

        @classmethod
        def from_str(cls, value):
            amount, currency = value.split()
            return cls(amount, currency)

    model = ModuleType("nautilus_trader.model")
    model.AccountType = _Value
    model.Currency = _Value
    model.FuturesContract = _FuturesContract
    model.InstrumentId = _InstrumentId
    model.Money = _Money
    model.OmsType = _Value
    model.PositionCostBasis = _Value
    model.TraderId = _Value
    model.Venue = _Value
    model.BookType = _Value
    model.OtoTriggerMode = _Value

    class _MarginModel:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    model.StandardMarginModel = _MarginModel
    model.LeveragedMarginModel = _MarginModel
    for name, module in {
        "nautilus_trader": root, "nautilus_trader.backtest": backtest,
        "nautilus_trader.config": config, "nautilus_trader.execution": execution,
        "nautilus_trader.model": model,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


def test_factory_builds_one_engine_and_one_account_per_venue(monkeypatch):
    _FakeEngine.instances.clear()
    _install_nautilus_fakes(monkeypatch)
    treasury = _FuturesContract("T2506.CFFEX")
    metal = _FuturesContract("AU2506.SHFE")
    engine = build_backtest_engine(_plan(), {
        "strategy:a": (treasury,), "strategy:b": (metal,),
    })

    assert len(_FakeEngine.instances) == 1
    assert engine is _FakeEngine.instances[0]
    assert {str(row["venue"]) for row in engine.venues} == {"CFFEX", "SHFE"}
    balances = {
        str(row["venue"]): row["starting_balances"][0].amount
        for row in engine.venues
    }
    assert balances == {"CFFEX": Decimal("600000"), "SHFE": Decimal("400000")}
    assert all(row["latency_model"] is None for row in engine.venues)
    assert engine.instruments == [treasury, metal]


def test_factory_registers_duplicate_instrument_only_once(monkeypatch):
    _install_nautilus_fakes(monkeypatch)
    instrument = _FuturesContract("T2506.CFFEX")
    engine = build_backtest_engine(_plan(), {
        "strategy:a": (instrument,), "strategy:b": (_FuturesContract("AU2506.SHFE"),),
    })
    assert len(engine.instruments) == 2


def test_factory_rejects_strategy_instrument_outside_frozen_venue_route(monkeypatch):
    _install_nautilus_fakes(monkeypatch)
    with pytest.raises(UnsupportedExecutionConfig, match="outside its frozen Venue route"):
        build_backtest_engine(_plan(), {
            "strategy:a": (_FuturesContract("AU2506.SHFE"),),
            "strategy:b": (_FuturesContract("AU2506.SHFE"),),
        })


def test_factory_requires_resolved_instruments_for_each_strategy():
    with pytest.raises(UnsupportedExecutionConfig, match="resolve every frozen strategy"):
        build_backtest_engine(_plan(), {"strategy:a": (_FuturesContract("T2506.CFFEX"),)})


def test_data_batch_is_added_once_to_the_single_engine():
    class Engine:
        def __init__(self):
            self.received = []

        def add_data_batch(self, batch, **kwargs):
            self.received.append((batch, kwargs))

    engine = Engine()
    batch = ["shared immutable marker"]
    add_data_batch(engine, batch)
    assert engine.received[0][0] is batch
    assert engine.received[0][1] == {"client_id": None, "validate": True, "sort": False}
