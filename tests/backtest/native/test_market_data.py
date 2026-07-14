from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.config import LedgerConfig
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.ledger import ledger_identity
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
import tools.testers.backtest.modules.market_data as market_data_module
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.market_data import (
    MarketDataModule, _build_trading_day_resolver, _causal_valuation, _check_market_data_coverage,
    _apply_exchange_rule_defaults, _desired_factor_frequencies,
    _historical_fields_at_from_frames, _load_raw_market_data,
    _resolve_market_data_request, _set_current_market_snapshot,
    contract_multiplier_from_fields,
    current_market_snapshot_at, current_prices_at, historical_fields_for_product,
    order_constraints_from_snapshot,
)
from tools.testers.backtest.modules.order_execution import OrderExecutionModule
from tools.data.types import DataColumn
from tools.data.types.time import DataTime
from tools.data.types.time_freq import DataFreq
from tools.data.field_history import (
    FieldHistoryProvider,
    HistoricalFieldFallbackPolicy,
    TimestampTradingDayResolver,
)
from tools.testers.backtest.modules.product_selection import ProductSelectionModule


def test_load_raw_market_data_reads_from_account_supplied_input():
    account = BacktestRunState()
    raw_prices = pd.DataFrame({"P1": [1.0, 2.0]}, index=pd.date_range("2024-01-01", periods=2))
    account.raw_market_data = {"raw_prices": raw_prices, "lot_sizes": {"P1": 5.0}}
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    _load_raw_market_data(account, ctx)
    assert ctx.get(MarketDataModule.raw_prices) is raw_prices
    assert ctx.get(MarketDataModule.lot_sizes) == {"P1": 5.0}


def test_market_data_store_guard_blocks_direct_runtime_writes_but_allows_publish_methods():
    account = BacktestRunState()
    store = account.market_data_store
    store.set_guarded_writes_enabled(True)
    prices = pd.DataFrame({"P1": [1.0]}, index=pd.date_range("2024-01-01", periods=1))

    with pytest.raises(RuntimeError, match="MarketDataStore.current_prices_table is guarded"):
        store.current_prices_table = prices

    store.publish_causal_valuation(prices)
    assert store.current_prices_table is prices

    store.set_guarded_writes_enabled(False)
    replacement = pd.DataFrame({"P1": [2.0]}, index=pd.date_range("2024-01-02", periods=1))
    store.current_prices_table = replacement
    assert store.current_prices_table is replacement


def test_load_raw_market_data_carries_price_limit_columns_into_order_constraints():
    class _Product:
        name = "P.XLIM"
        exchange_id = "XLIM"
        desc = "测试品种"

        def __init__(self):
            self.MIN1 = self

        def list_available_freqs(self):
            return [DataFreq.MIN1]

        def get_and_adjust_cols(self, columns, **_kwargs):
            index = pd.date_range("2024-01-01 09:01", periods=1, freq="1min")
            frame = pd.DataFrame({
                DataColumn.OPEN.name: [10.0],
                DataColumn.HIGH.name: [10.0],
                DataColumn.LOW.name: [10.0],
                DataColumn.CLOSE.name: [10.0],
                DataColumn.VWAP.name: [10.0],
                DataColumn.VOLUME.name: [1.0],
                DataColumn.UPPER_LIMIT_PRICE.name: [10.0],
                DataColumn.LOWER_LIMIT_PRICE.name: [8.0],
            }, index=index)
            return frame.loc[:, [column for column in columns if column in frame.columns]]

    from tools.traderules import ExchangeTradingRule, register_exchange_trading_rule

    register_exchange_trading_rule(ExchangeTradingRule(
        exchange_id="XLIM",
        tradability_policy="valid_close_and_price_limits",
    ))
    product = _Product()
    account = BacktestRunState()
    account.market_data_store.load_plan = [(product, DataFreq.MIN1, None)]
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _load_raw_market_data(account, ctx)
    _causal_valuation(account, ctx)
    snapshot = current_market_snapshot_at(account, pd.Timestamp("2024-01-01 09:01"))
    constraints = order_constraints_from_snapshot(snapshot)

    assert snapshot["upper_limit"][product] == 10.0
    assert constraints[product].can_buy is False
    assert constraints[product].can_sell is True


def test_current_market_snapshot_is_cached_per_event_timestamp(monkeypatch):
    account = BacktestRunState()
    timestamp = pd.Timestamp("2024-01-01 09:01", tz="Asia/Shanghai")
    calls = {"prices": 0}
    product = object()

    def _prices(_state, _timestamp):
        calls["prices"] += 1
        return {product: 10.0}

    monkeypatch.setattr(market_data_module, "current_prices_at", _prices)
    monkeypatch.setattr(market_data_module, "market_price_tables_for", lambda _state: {})
    monkeypatch.setattr(market_data_module, "current_volume_at", lambda _state, _timestamp: {})

    first = market_data_module.current_market_snapshot_at(account, timestamp)
    second = market_data_module.current_market_snapshot_at(account, timestamp)

    assert first is second
    assert calls["prices"] == 1


def test_current_historical_fields_is_cached_per_event_timestamp(monkeypatch):
    product = object()
    timestamp = pd.Timestamp("2024-01-01 09:01", tz="Asia/Shanghai")
    account = BacktestRunState()
    account.market_data_store.historical_field_names = ("VolumeMultiple",)
    account.market_data_store.historical_field_provider = object()
    account.market_data_store.trading_day_resolver = object()
    account.market_data_store.historical_field_frames = {"VolumeMultiple": pd.DataFrame()}
    account.market_data_store.current_prices_table = pd.DataFrame({product: [10.0]}, index=[timestamp])
    calls = {"frames": 0}

    def _from_frames(_frames, instruments, _timestamp, **_kwargs):
        calls["frames"] += 1
        return {instrument: {"VolumeMultiple": 1.0} for instrument in instruments}

    monkeypatch.setattr(market_data_module, "_historical_fields_at_from_frames", _from_frames)

    first = market_data_module.current_historical_fields_at(account, timestamp)
    second = market_data_module.current_historical_fields_at(account, timestamp)

    assert first is second
    assert first[product]["VolumeMultiple"] == 1.0
    assert calls["frames"] == 1


def test_current_historical_fields_reuses_cache_for_causal_epsilon(monkeypatch):
    product = object()
    timestamp = pd.Timestamp("2024-01-01 09:01:00", tz="Asia/Shanghai")
    account = BacktestRunState()
    account.market_data_store.historical_field_names = ("VolumeMultiple",)
    account.market_data_store.historical_field_provider = object()
    account.market_data_store.trading_day_resolver = object()
    account.market_data_store.historical_field_frames = {"VolumeMultiple": pd.DataFrame()}
    account.market_data_store.current_prices_table = pd.DataFrame({product: [10.0]}, index=[timestamp])
    calls = {"frames": 0}

    def _from_frames(_frames, instruments, _timestamp, **_kwargs):
        calls["frames"] += 1
        return {instrument: {"VolumeMultiple": 1.0} for instrument in instruments}

    monkeypatch.setattr(market_data_module, "_historical_fields_at_from_frames", _from_frames)

    first = market_data_module.current_historical_fields_at(account, timestamp)
    second = market_data_module.current_historical_fields_at(account, timestamp + pd.Timedelta(1, "ns"))
    third = market_data_module.current_historical_fields_at(account, timestamp + pd.Timedelta(2, "ns"))

    assert first is second is third
    assert calls["frames"] == 1


def test_historical_fields_frame_row_cache_reuses_same_effective_rule_row():
    product = object()
    account = BacktestRunState()
    account.market_data_store.historical_field_names = ("VolumeMultiple",)
    account.market_data_store.historical_field_provider = object()
    account.market_data_store.trading_day_resolver = object()
    account.market_data_store.current_prices_table = pd.DataFrame(
        {product: [10.0, 11.0, 12.0]},
        index=pd.date_range("2024-01-01 09:01", periods=3, freq="1min", tz="Asia/Shanghai"),
    )
    account.market_data_store.historical_field_frames = {
        "VolumeMultiple": pd.DataFrame(
            {str(product): [1.0, 2.0]},
            index=pd.DatetimeIndex(["2024-01-01 09:00", "2024-01-01 09:03"]),
        )
    }

    first = market_data_module.current_historical_fields_at(
        account,
        pd.Timestamp("2024-01-01 09:01", tz="Asia/Shanghai"),
    )
    second = market_data_module.current_historical_fields_at(
        account,
        pd.Timestamp("2024-01-01 09:02", tz="Asia/Shanghai"),
    )
    changed = market_data_module.current_historical_fields_at(
        account,
        pd.Timestamp("2024-01-01 09:03", tz="Asia/Shanghai"),
    )

    assert first is second
    assert first[product]["VolumeMultiple"] == 1.0
    assert changed is not first
    assert changed[product]["VolumeMultiple"] == 2.0


def test_field_change_event_updates_field_state_store_for_later_materialization():
    class _Product:
        name = "P1.CFE"

    product = _Product()
    timestamp = pd.Timestamp("2026-01-05 09:01:00", tz="Asia/Shanghai")
    state = BacktestRunState()
    state.market_data_store.historical_field_names = ("VolumeMultiple",)
    state.market_data_store.historical_field_provider = object()
    state.market_data_store.trading_day_resolver = object()
    state.market_data_store.field_state_store = {"P1.CFE": {"VolumeMultiple": 10.0}}
    state.market_data_store.current_prices_table = pd.DataFrame({product: [100.0]}, index=[timestamp])
    strategy = Strategy(alias="A1")
    ctx = FlowContext(
        timestamp=timestamp,
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
        drafts_by_strategy={
            strategy: [
                EventDraft(
                    EventKind.FIELD_CHANGE,
                    timestamp,
                    strategy=strategy,
                    payload={"changes": {"P1.CFE": {"VolumeMultiple": 20.0}}},
                )
            ]
        },
        event_kind=EventKind.FIELD_CHANGE,
    )

    market_data_module._handle_field_changes(state, ctx)
    state.market_data_store.historical_fields_cache.clear()

    fields = market_data_module.current_historical_fields_at(state, timestamp)

    assert state.market_data_store.field_state_store["P1.CFE"]["VolumeMultiple"] == 20.0
    assert fields[product]["VolumeMultiple"] == 20.0


def test_order_event_current_prices_use_open_snapshot_not_close_snapshot():
    product = object()
    timestamp = pd.Timestamp("2024-01-01 09:01", tz="Asia/Shanghai")
    account = BacktestRunState()
    account.market_data_store.current_prices_table = pd.DataFrame(
        {product: [11.0]},
        index=[timestamp],
    )
    account.market_data_store.market_price_tables = {
        "open": pd.DataFrame({product: [10.0]}, index=[timestamp]),
        "close": pd.DataFrame({product: [11.0]}, index=[timestamp]),
    }

    order_ctx = FlowContext(timestamp=timestamp, event_queue=EventQueue(), event_kind=EventKind.ORDER)
    _set_current_market_snapshot(account, order_ctx)
    signal_ctx = FlowContext(timestamp=timestamp, event_queue=EventQueue(), event_kind=EventKind.SIGNAL)
    _set_current_market_snapshot(account, signal_ctx)

    assert order_ctx.get(MarketDataModule.current_prices)[product] == 10.0
    assert signal_ctx.get(MarketDataModule.current_prices)[product] == 11.0


def test_order_event_uses_order_price_timestamp_for_market_snapshot():
    product = object()
    idx = pd.date_range("2024-01-01 09:01", periods=2, freq="1min", tz="Asia/Shanghai")
    strategy = Strategy(alias="order")
    account = BacktestRunState(strategy_configs={strategy: StrategyConfig(strategy=strategy)})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {product: [11.0, 21.0]},
        index=idx,
    )
    account.market_data_store.market_price_tables = {
        "open": pd.DataFrame({product: [10.0, 20.0]}, index=idx),
        "close": pd.DataFrame({product: [11.0, 21.0]}, index=idx),
    }
    class OrderLike:
        def get(self, key: str, default: Any = None) -> Any:
            return idx[1] if key == "price_timestamp" else default

    order = OrderLike()
    ctx = FlowContext(
        timestamp=idx[0] + pd.Timedelta(microseconds=1),
        event_queue=EventQueue(),
        event_kind=EventKind.ORDER,
        active_strategies=frozenset((strategy,)),
        drafts_by_strategy={strategy: [EventDraft(EventKind.ORDER, idx[0] + pd.Timedelta(microseconds=1), strategy, order)]},
    )

    _set_current_market_snapshot(account, ctx)

    assert ctx.get(MarketDataModule.current_prices)[product] == 20.0
    assert ctx.get(MarketDataModule.current_market_snapshot)["close"][product] == 21.0


def test_order_event_minimal_snapshot_uses_policy_price_basis_and_limit_fields():
    product = object()
    idx = pd.date_range("2024-01-01 09:01", periods=2, freq="1min", tz="Asia/Shanghai")
    strategy = Strategy(alias="order")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy, field_values={
            OrderExecutionModule.execution_price_basis: "vwap",
        })
    })
    account.market_data_store.current_prices_table = pd.DataFrame({product: [11.0, 21.0]}, index=idx)
    account.market_data_store.market_price_tables = {
        "open": pd.DataFrame({product: [10.0, 20.0]}, index=idx),
        "vwap": pd.DataFrame({product: [10.5, 20.5]}, index=idx),
        "close": pd.DataFrame({product: [11.0, 21.0]}, index=idx),
        "upper_limit": pd.DataFrame({product: [12.0, 22.0]}, index=idx),
        "lower_limit": pd.DataFrame({product: [9.0, 19.0]}, index=idx),
        "settlement": pd.DataFrame({product: [99.0, 199.0]}, index=idx),
    }

    class OrderLike:
        def get(self, key: str, default: Any = None) -> Any:
            return idx[1] if key == "price_timestamp" else default

    ctx = FlowContext(
        timestamp=idx[0] + pd.Timedelta(microseconds=1),
        event_queue=EventQueue(),
        event_kind=EventKind.ORDER,
        active_strategies=frozenset((strategy,)),
        drafts_by_strategy={strategy: [EventDraft(EventKind.ORDER, idx[0] + pd.Timedelta(microseconds=1), strategy, OrderLike())]},
    )

    _set_current_market_snapshot(account, ctx)
    snapshot = ctx.get(MarketDataModule.current_market_snapshot)

    assert ctx.get(MarketDataModule.current_prices)[product] == 20.5
    assert snapshot["vwap"][product] == 20.5
    assert snapshot["close"][product] == 21.0
    assert snapshot["upper_limit"][product] == 22.0
    assert snapshot["lower_limit"][product] == 19.0
    assert "settlement" not in snapshot


def test_order_event_does_not_fallback_open_price_basis_to_close():
    class _Product:
        name = "P.TEST"
        desc = "测试"

    product = _Product()
    idx = pd.date_range("2024-01-01 09:01", periods=1, freq="1min", tz="Asia/Shanghai")
    strategy = Strategy(alias="order")
    account = BacktestRunState(strategy_configs={strategy: StrategyConfig(strategy=strategy)})
    account.market_data_store.current_prices_table = pd.DataFrame({product: [11.0]}, index=idx)
    account.market_data_store.market_price_tables = {
        "close": pd.DataFrame({product: [11.0]}, index=idx),
    }

    class OrderLike:
        instrument = product

        def get(self, key: str, default: Any = None) -> Any:
            return idx[0] if key == "price_timestamp" else default

    ctx = FlowContext(
        timestamp=idx[0] + pd.Timedelta(microseconds=1),
        event_queue=EventQueue(),
        event_kind=EventKind.ORDER,
        active_strategies=frozenset((strategy,)),
        drafts_by_strategy={
            strategy: [EventDraft(EventKind.ORDER, idx[0] + pd.Timedelta(microseconds=1), strategy, OrderLike())],
        },
    )

    _set_current_market_snapshot(account, ctx)

    assert ctx.get(MarketDataModule.current_prices) == {}
    assert not [row for row in account.runtime_info_rows if row.get("code") == "order_price_basis_fallback"]


def test_signal_event_minimal_snapshot_matches_relevant_full_snapshot_fields():
    product = object()
    timestamp = pd.Timestamp("2024-01-01 09:01", tz="Asia/Shanghai")
    account = BacktestRunState()
    account.market_data_store.current_prices_table = pd.DataFrame({product: [11.0]}, index=[timestamp])
    account.market_data_store.volume_table = pd.DataFrame({product: [100.0]}, index=[timestamp])
    account.market_data_store.market_price_tables = {
        "open": pd.DataFrame({product: [10.0]}, index=[timestamp]),
        "close": pd.DataFrame({product: [11.0]}, index=[timestamp]),
        "upper_limit": pd.DataFrame({product: [12.0]}, index=[timestamp]),
        "lower_limit": pd.DataFrame({product: [9.0]}, index=[timestamp]),
        "settlement": pd.DataFrame({product: [99.0]}, index=[timestamp]),
    }

    full = current_market_snapshot_at(account, timestamp)
    account.market_data_store.market_snapshot_cache.clear()
    ctx = FlowContext(timestamp=timestamp, event_queue=EventQueue(), event_kind=EventKind.SIGNAL)
    _set_current_market_snapshot(account, ctx)
    signal = ctx.get(MarketDataModule.current_market_snapshot)

    for key in ("close", "volume", "upper_limit", "lower_limit"):
        assert signal[key] == full[key]
    assert "open" not in signal
    assert "settlement" not in signal


def test_ledger_event_minimal_snapshot_matches_settlement_and_close_only():
    product = object()
    timestamp = pd.Timestamp("2024-01-01 15:00", tz="Asia/Shanghai")
    account = BacktestRunState()
    account.market_data_store.current_prices_table = pd.DataFrame({product: [11.0]}, index=[timestamp])
    account.market_data_store.volume_table = pd.DataFrame({product: [100.0]}, index=[timestamp])
    account.market_data_store.market_price_tables = {
        "open": pd.DataFrame({product: [10.0]}, index=[timestamp]),
        "close": pd.DataFrame({product: [11.0]}, index=[timestamp]),
        "upper_limit": pd.DataFrame({product: [12.0]}, index=[timestamp]),
        "lower_limit": pd.DataFrame({product: [9.0]}, index=[timestamp]),
        "settlement": pd.DataFrame({product: [99.0]}, index=[timestamp]),
    }

    full = current_market_snapshot_at(account, timestamp)
    account.market_data_store.market_snapshot_cache.clear()
    ctx = FlowContext(timestamp=timestamp, event_queue=EventQueue(), event_kind=EventKind.LEDGER)
    _set_current_market_snapshot(account, ctx)
    ledger = ctx.get(MarketDataModule.current_market_snapshot)

    assert ledger["close"] == full["close"]
    assert ledger["settlement"] == full["settlement"]
    assert ctx.get(MarketDataModule.current_prices) == full["close"]
    assert ctx.get(MarketDataModule.current_tradable_status) == {}
    assert ctx.get(MarketDataModule.current_order_constraints) == {}
    assert "open" not in ledger
    assert "volume" not in ledger
    assert "upper_limit" not in ledger
    assert "lower_limit" not in ledger


def test_bar_open_event_uses_target_index_key_not_visible_timestamp():
    product = object()
    idx = pd.date_range("2024-01-01 09:01", periods=2, freq="1min", tz="Asia/Shanghai")
    strategy = Strategy(alias="live")
    account = BacktestRunState(strategy_configs={strategy: StrategyConfig(strategy=strategy)})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {product: [11.0, 21.0]},
        index=idx,
    )
    account.market_data_store.market_price_tables = {
        "open": pd.DataFrame({product: [10.0, 20.0]}, index=idx),
        "close": pd.DataFrame({product: [11.0, 21.0]}, index=idx),
    }
    ctx = FlowContext(
        timestamp=idx[0] + pd.Timedelta(microseconds=1),
        event_queue=EventQueue(),
        event_kind=EventKind.BAR,
        active_strategies=frozenset((strategy,)),
        drafts_by_strategy={
            strategy: [EventDraft(
                EventKind.BAR,
                idx[0] + pd.Timedelta(microseconds=1),
                strategy,
                payload={"bar_basis": "open"},
                index_key=idx[1],
            )],
        },
    )

    _set_current_market_snapshot(account, ctx)

    assert ctx.get(MarketDataModule.current_prices)[product] == 20.0
    assert ctx.get(MarketDataModule.current_market_snapshot)["close"][product] == 21.0


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
    assert ctx.get(MarketDataModule.market_data_load_plan) == {
        "type": "MarketDataLoadPlan",
        "items": {"P1": {"frequency": "MIN1", "data_source": "auto"}},
        "count": 1,
    }
    assert ctx.get(MarketDataModule.excluded_out_of_range_products) == {
        "type": "MarketDataExcludedProducts",
        "rows": [],
        "count": 0,
    }


def test_check_market_data_coverage_declares_load_plan_outputs():
    assert MarketDataModule.market_data_load_plan in MarketDataModule.check_market_data_coverage.outputs
    assert MarketDataModule.excluded_out_of_range_products in MarketDataModule.check_market_data_coverage.outputs


def test_causal_valuation_flow_description_names_forward_fill_semantics():
    assert MarketDataModule.causal_valuation.description == "市场价格向前填充"


def test_check_market_data_coverage_reports_raw_market_data_seed_as_load_plan():
    account = BacktestRunState()
    account.raw_market_data = {
        "raw_prices": pd.DataFrame({"P1": [1.0], "P2": [2.0]}, index=pd.date_range("2024-01-01", periods=1)),
        "excluded_out_of_range_products": ("P3",),
    }
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _check_market_data_coverage(account, ctx)

    assert ctx.get(MarketDataModule.market_data_load_plan) == {
        "type": "MarketDataLoadPlan",
        "items": {
            "P1": {"frequency": "provided", "data_source": "raw_market_data"},
            "P2": {"frequency": "provided", "data_source": "raw_market_data"},
        },
        "count": 2,
    }
    assert ctx.get(MarketDataModule.excluded_out_of_range_products) == {
        "type": "MarketDataExcludedProducts",
        "rows": [{"product": "P3"}],
        "count": 1,
    }


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


def test_check_market_data_coverage_excludes_out_of_range_product_before_frequency_error(monkeypatch):
    class _Product:
        name = "ER.CZC"
        desc = "早籼稻"

        def list_available_freqs(self):
            return [DataFreq.DAY1]

    product = _Product()
    s1 = Strategy(alias="A1")
    s2 = Strategy(alias="A2")
    account = BacktestRunState(strategy_configs={
        s1: StrategyConfig(strategy=s1),
        s2: StrategyConfig(strategy=s2),
    })
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    for strategy in (s1, s2):
        ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))
        ctx.set_for(MarketDataModule.required_frequency, strategy, DataFreq.MIN1)
        ctx.set_for(MarketDataModule.required_data_source, strategy, ())
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._product_outside_run_window",
        lambda item, start_dt, end_dt: item is product,
    )

    _check_market_data_coverage(account, ctx)

    assert account.market_data_store.load_plan == []
    assert account.market_data_store.excluded_out_of_range == (product,)
    assert len(account.runtime_info_rows) == 1
    assert account.runtime_info_rows[0]["details"]["product_names"] == ["ER.CZC"]


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


def test_resolve_market_data_request_keeps_required_frequency_strategy_scoped_when_uniform():
    class _Product:
        name = "P1"

        def list_available_freqs(self):
            return [DataFreq.MIN1]

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
            MarketDataModule.freq_fixed: "MIN1",
        }),
    })
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s1, frozenset({product}))
    ctx.set_for(ProductSelectionModule.products, s2, frozenset({product}))

    _resolve_market_data_request(account, ctx)

    assert ctx.get_for(MarketDataModule.required_frequency, s1) == DataFreq.MIN1
    assert ctx.get_for(MarketDataModule.required_frequency, s2) == DataFreq.MIN1
    assert ctx.get(MarketDataModule.required_frequency) is None
    assert account.market_data_store.required_frequency_by_strategy == {
        s1: DataFreq.MIN1,
        s2: DataFreq.MIN1,
    }


def test_desired_factor_frequencies_does_not_default_to_min1_without_factor_requirements():
    factor = object()

    assert _desired_factor_frequencies(factor) == set()


def test_infer_market_data_request_uses_available_common_frequency_without_min1_default():
    class _Product:
        name = "P1"

        def list_available_freqs(self):
            return [DataFreq.DAY1]

    strategy = Strategy(alias="S1")
    product = _Product()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy, field_values={
            MarketDataModule.freq_mode: "auto",
            FactorModule.factor: object(),
        }),
    })
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _resolve_market_data_request(account, ctx)

    assert ctx.get_for(MarketDataModule.required_frequency, strategy) == DataFreq.DAY1
    assert ctx.get(MarketDataModule.required_frequency) is None


def test_check_market_data_coverage_unifies_compatible_frequency_requests(monkeypatch):
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

    _check_market_data_coverage(account, ctx)

    assert account.market_data_store.load_plan == [(product, DataFreq.MIN1, None)]


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
    price_tables = ctx.get(MarketDataModule.price_tables)
    assert set(price_tables) >= {"open", "high", "low", "close", "vwap"}
    assert price_tables["open"][product].tolist() == [10.0, 20.0]


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
    min1_times = pd.date_range("2024-01-01 09:01", periods=2, freq="1min")
    min1_frame = pd.DataFrame(
        price_columns,
        index=pd.MultiIndex.from_arrays(
            [min1_times.normalize(), min1_times],
            names=["DAY1", "MIN1"],
        ),
    )
    day1_frame = pd.DataFrame(
        {
            "OPEN": [100.0],
            "HIGH": [110.0],
            "LOW": [90.0],
            "CLOSE": [105.0],
            "VWAP": [102.5],
        },
        index=pd.DatetimeIndex([pd.Timestamp("2024-01-01 15:00", tz="Asia/Shanghai")]),
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
    assert not isinstance(raw_prices.index, pd.MultiIndex)
    assert str(raw_prices.index.tz) == "Asia/Shanghai"
    _build_trading_day_resolver(account, ctx)
    resolver = ctx.get(MarketDataModule.trading_day_resolver)
    assert resolver.resolve_trading_day(pd.Timestamp("2024-01-01 09:01")) == pd.Timestamp("2024-01-01")
    assert account.market_data_store.market_price_tables["open"][p1].dropna().tolist() == [10.0, 20.0]
    assert account.market_data_store.market_price_tables["open"][p2].dropna().tolist() == [100.0]


def test_load_raw_market_data_expands_for_live_strategy_warmup_only():
    class _Product:
        name = "P1"
        desc = "P1"

        def __init__(self) -> None:
            self.MIN1 = self
            self.calls: list[dict[str, object]] = []

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


def test_historical_fields_for_product_lookup_matches_legacy_scan_without_mutating_input():
    class _Product:
        name = "RU.SHF"
        alias = "RU.SHF"
        code = "RU"

        def __str__(self) -> str:
            return self.name

    product = _Product()
    fields = {"VolumeMultiple": 10.0}
    historical_fields: dict[Any, dict[str, object]] = {
        "AP.CZC": {"VolumeMultiple": 5.0},
        product: fields,
    }
    original_keys = tuple(historical_fields.keys())

    def _legacy_scan(target: Any) -> dict[str, object]:
        target_keys = market_data_module._historical_field_product_keys(target)
        for instrument, values in historical_fields.items():
            if target_keys & market_data_module._historical_field_product_keys(instrument):
                return values
        return {}

    assert historical_fields_for_product(historical_fields, "RU.SHF") is _legacy_scan("RU.SHF")
    assert historical_fields_for_product(historical_fields, product) is _legacy_scan(product)
    assert tuple(historical_fields.keys()) == original_keys


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


def test_historical_fields_at_reuses_frame_column_cache():
    class Product:
        name = "EG.DCE"

        def __str__(self):
            return "EG.DCE"

    product = Product()
    frame_ts = pd.Timestamp("2026-01-05 09:01:00")
    event_ts = cast(pd.Timestamp, pd.Timestamp("2026-01-05 09:01:00", tz="Asia/Shanghai"))
    frames = {
        "OpenRatioByMoney": pd.DataFrame({"EG.DCE": [0.0001]}, index=pd.DatetimeIndex([frame_ts])),
        "VolumeMultiple": pd.DataFrame({"EG.DCE": [10]}, index=pd.DatetimeIndex([frame_ts])),
    }
    column_cache: dict[tuple[str, tuple[str, ...]], object | None] = {}

    first = _historical_fields_at_from_frames(frames, [product], event_ts, column_cache=column_cache)
    second = _historical_fields_at_from_frames(frames, [product], event_ts, column_cache=column_cache)

    assert first[product]["OpenRatioByMoney"] == second[product]["OpenRatioByMoney"] == 0.0001
    assert first[product]["VolumeMultiple"] == second[product]["VolumeMultiple"] == 10
    assert column_cache == {
        ("OpenRatioByMoney", ("EG.DCE",)): "EG.DCE",
        ("VolumeMultiple", ("EG.DCE",)): "EG.DCE",
    }


def test_historical_fields_at_does_not_look_ahead_before_first_row():
    frame_ts = pd.Timestamp("2026-01-05 09:01:00")
    event_ts = cast(pd.Timestamp, pd.Timestamp("2026-01-05 09:00:59.999999999", tz="Asia/Shanghai"))
    frames = {
        "OpenRatioByMoney": pd.DataFrame({"EG.DCE": [0.0001]}, index=pd.DatetimeIndex([frame_ts])),
    }

    fields = _historical_fields_at_from_frames(frames, ["EG.DCE"], event_ts)

    assert fields["EG.DCE"] == {}


def test_exchange_rule_defaults_fill_missing_historical_fields_without_overwrite():
    from sources.LocalCNFutures.clearing_rules import register_local_cnfutures_exchange_rules

    register_local_cnfutures_exchange_rules()
    state = BacktestRunState()
    timestamp = pd.Timestamp("2026-01-05 09:01:00", tz="Asia/Shanghai")

    result = _apply_exchange_rule_defaults(
        state,
        {
            "AP.CZC": {"CostBasisMethod": None, "MoneyCalculationPolicy": ""},
            "RU.SHF": {"MoneyCalculationPolicy": "per_contract_price_point"},
            "SM.CZC": {"CostBasisMethod": np.nan},
        },
        ["AP.CZC", "RU.SHF", "SM.CZC"],
        ("CostBasisMethod", "MoneyCalculationPolicy"),
        timestamp,
    )

    assert result["AP.CZC"]["CostBasisMethod"] == "DailyMarkToMarket"
    assert result["AP.CZC"]["MoneyCalculationPolicy"] == "aggregate"
    assert result["RU.SHF"]["CostBasisMethod"] == "DailyMarkToMarket"
    assert result["RU.SHF"]["MoneyCalculationPolicy"] == "per_contract_price_point"
    assert result["SM.CZC"]["CostBasisMethod"] == "DailyMarkToMarket"
    rows = [row for row in state.runtime_info_rows if row.get("code") == "historical_field_default_fallback"]
    assert rows == []


def test_contract_multiplier_default_fallback_records_runtime_info_interval():
    class _Product:
        name = "P.MULT"
        desc = "乘数测试"

    product = _Product()
    state = BacktestRunState()

    first = contract_multiplier_from_fields(
        {product: {"VolumeMultiple": None}},
        product,
        state=state,
        timestamp=pd.Timestamp("2026-01-05 09:01:00", tz="Asia/Shanghai"),
    )
    second = contract_multiplier_from_fields(
        {product: {"VolumeMultiple": np.nan}},
        product,
        state=state,
        timestamp=pd.Timestamp("2026-01-05 09:02:00", tz="Asia/Shanghai"),
    )

    assert first == second == 1.0
    rows = [row for row in state.runtime_info_rows if row.get("code") == "contract_multiplier_default_fallback"]
    assert len(rows) == 1
    assert rows[0]["details"]["product"] == "P.MULT"
    assert rows[0]["details"]["source"] == "VolumeMultiple"
    assert rows[0]["details"]["fallback"] == "default:1"
    assert rows[0]["details"]["count"] == 2


def test_latest_available_historical_field_backfill_records_runtime_info():
    class _Product:
        name = "CF.CZC"
        desc = "棉花"

    product = _Product()
    timestamp = pd.Timestamp("2021-01-05 09:01:00", tz="Asia/Shanghai")
    state = BacktestRunState()
    state.market_data_store.current_prices_table = pd.DataFrame(
        {product: [15000.0]},
        index=pd.DatetimeIndex([timestamp]),
    )
    state.market_data_store.historical_field_names = ("MaxLimitOrderVolume",)
    state.market_data_store.historical_field_policy = HistoricalFieldFallbackPolicy.LATEST_AVAILABLE.value
    state.market_data_store.historical_field_provider = FieldHistoryProvider.from_records([
        {
            "provider": "Agent:CZCE",
            "source_key": "agent/CZCE/max-limit-order-volume-2022",
            "instrument": "*",
            "instrument_label": "郑商所期货默认",
            "instrument_type": "future",
            "scope_type": "exchange_default",
            "exchange": "CZC",
            "field_name": "MaxLimitOrderVolume",
            "effective_trading_day": "2022-12-01",
            "effective_timestamp": "2022-12-01 09:00:00",
            "value": 1000,
            "contract_scope_type": "all",
            "change_type": "baseline",
            "source_notice_id": "郑商所公告〔2022〕74号",
            "source_url": "https://www.czce.com.cn/",
        }
    ])
    state.market_data_store.trading_day_resolver = TimestampTradingDayResolver({
        timestamp: pd.Timestamp("2021-01-05"),
    })

    fields = market_data_module.current_historical_fields_at(state, timestamp)

    assert fields[product]["MaxLimitOrderVolume"] == 1000
    rows = [
        row for row in state.runtime_info_rows
        if row.get("code") == "historical_field_latest_available_backfill"
    ]
    assert len(rows) == 1
    assert rows[0]["details"]["product"] == "CF.CZC"
    assert rows[0]["details"]["source"] == "MaxLimitOrderVolume"
    assert rows[0]["details"]["fallback"].startswith("latest_available:")


def test_auto_accounting_subscribes_cost_basis_method_for_market_data():
    from tools.testers.backtest.engines.native.state import BacktestRunState
    from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
    from tools.testers.backtest.engines.native.ledger import ledger_identity
    from tools.testers.backtest.modules.engine import EngineModule
    from tools.testers.backtest.modules.market_data import _required_market_rule_field_names

    strategy = Strategy(alias="auto")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy, field_values={EngineModule.engine_mode: "auto"}),
    })

    fields = _required_market_rule_field_names(account)

    assert "CostBasisMethod" in fields
    assert "MoneyCalculationPolicy" in fields


def test_fee_zero_does_not_subscribe_transaction_fee_fields_for_auto_accounting():
    from tools.data.field_history import TRANSACTION_FEE_FIELD_NAMES
    from tools.testers.backtest.engines.native.state import BacktestRunState
    from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
    from tools.testers.backtest.modules.engine import EngineModule
    from tools.testers.backtest.modules.fee import FeeModule
    from tools.testers.backtest.modules.market_data import _required_market_rule_field_names
    from tools.testers.backtest.modules.trading_rule import TradingRuleModule

    strategy = Strategy(alias="zero-fee")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy, field_values={
            EngineModule.engine_mode: "custom",
            TradingRuleModule.accounting_mode: "Auto",
        }),
    })
    ledger = account.ledger_for_strategy(strategy).ledger
    account.ledger_configs[ledger] = LedgerConfig(fee_mode="zero", accounting_mode="Auto")

    fields = set(_required_market_rule_field_names(account))

    assert "CostBasisMethod" in fields
    assert "MoneyCalculationPolicy" in fields
    assert not (set(TRANSACTION_FEE_FIELD_NAMES) & fields)


def test_historical_field_frames_for_market_data_reuses_identical_run_cache(monkeypatch):
    import tools.testers.backtest.modules.market_data as market_data_module

    class Product:
        name = "AP.CZC"

        def __str__(self):
            return self.name

    calls = {"frames": 0}
    index = pd.date_range("2026-01-05 09:01", periods=2, freq="1min", tz="Asia/Shanghai")
    expected = {"VolumeMultiple": pd.DataFrame({"AP.CZC": [10, 10]}, index=index)}

    def _fake_frame_for_products(*args, **kwargs):
        calls["frames"] += 1
        return expected

    monkeypatch.setattr(market_data_module, "historical_fields_frame_for_products", _fake_frame_for_products)
    market_data_module._HISTORICAL_FIELDS_FRAME_CACHE.clear()
    product = Product()

    first = market_data_module.historical_field_frames_for_market_data(
        [product],
        index,
        provider=cast(Any, object()),
        trading_day_resolver=cast(Any, object()),
        field_names=("VolumeMultiple",),
        policy="latest_available",
    )
    second = market_data_module.historical_field_frames_for_market_data(
        [product],
        index,
        provider=cast(Any, object()),
        trading_day_resolver=cast(Any, object()),
        field_names=("VolumeMultiple",),
        policy="latest_available",
    )

    assert first is second is expected
    assert calls["frames"] == 1


def test_set_current_historical_fields_skips_per_strategy_write_when_nothing_customizes():
    """Every consumer of current_historical_fields reads via
    ctx.get_for(ref, strategy, ctx.get(ref, {})) -- a strategy that doesn't
    customize should never get a per-strategy ctx.set_for entry at all (it
    would just be an identical copy of base_fields under a redundant key);
    it should transparently fall through to the one shared base_fields
    object via that fallback. A strategy that genuinely customizes should
    still get its own distinct per-strategy entry."""
    from tools.testers.backtest.engines.native.state import BacktestRunState
    from tools.testers.backtest.engines.native.config import StrategyConfig
    from tools.testers.backtest.modules.custom_product import CustomProductModule
    from tools.testers.backtest.modules.engine import EngineModule
    from tools.testers.backtest.modules.fee import FeeModule
    from tools.testers.backtest.modules.market_data import _set_current_historical_fields

    plain = Strategy(alias="plain")
    custom = Strategy(alias="custom")
    plain_config = StrategyConfig(strategy=plain, field_values={})
    custom_config = StrategyConfig(strategy=custom, field_values={
        EngineModule.engine_mode: "custom",
        FeeModule.fee_mode: "custom",
        CustomProductModule.custom_product_fields: [
            {"product": "P1", "field": "VolumeMultiple", "value": 5.0},
        ],
    })
    account = BacktestRunState(strategy_configs={plain: plain_config, custom: custom_config})
    account.ledger_configs[ledger_identity(f"private:{custom.alias}")] = LedgerConfig(fee_mode="custom")
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-01-01"), event_queue=EventQueue(),
        active_strategies=frozenset({plain, custom}),
    )

    _set_current_historical_fields(account, ctx)

    sentinel = object()
    assert ctx.get_for(MarketDataModule.current_historical_fields, plain, sentinel) is sentinel

    base_fields = ctx.get(MarketDataModule.current_historical_fields)
    resolved_for_plain = ctx.get_for(
        MarketDataModule.current_historical_fields, plain,
        ctx.get(MarketDataModule.current_historical_fields, {}),
    )
    assert resolved_for_plain is base_fields

    resolved_for_custom = ctx.get_for(MarketDataModule.current_historical_fields, custom, sentinel)
    assert resolved_for_custom is not sentinel
    assert resolved_for_custom is not base_fields
    assert resolved_for_custom["P1"]["VolumeMultiple"] == 5.0
