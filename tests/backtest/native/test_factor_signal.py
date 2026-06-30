from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from tools.data.types import DataColumn
from tools.factors.expr import ColumnRef
from tools.data.types.time_freq import DataFreq
from tools.testers.backtest.engines.native.ledger import AccountState, StrategyConfig
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.fields import FieldRef
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.factor_signal import (
    FactorSignalModule, _evaluate_signal_live, _observe_signal_live_bar,
    _schedule_signal_live_timestamps, _schedule_signal_precomputed_timestamps,
    normalize_signal_timestamp,
)


class _FakeMinuteFreq:
    def is_day_multiple(self) -> bool:
        return False


class _FakeDayFreq:
    def is_day_multiple(self) -> bool:
        return True


def test_normalize_signal_timestamp_minute_level_floors_seconds():
    ts = pd.Timestamp("2024-01-01 14:30:45.123")
    result = normalize_signal_timestamp(ts, _FakeMinuteFreq())
    assert result == pd.Timestamp("2024-01-01 14:30:00")


def test_normalize_signal_timestamp_day_level_with_time_component_same_rule():
    ts = pd.Timestamp("2024-01-01 15:00:30")
    result = normalize_signal_timestamp(ts, _FakeDayFreq())
    assert result == pd.Timestamp("2024-01-01 15:00:00")


def test_normalize_signal_timestamp_day_level_midnight_uses_lookup():
    ts = pd.Timestamp("2024-01-01 00:00:00")
    result = normalize_signal_timestamp(
        ts, _FakeDayFreq(), last_minute_lookup=lambda t: pd.Timestamp("2024-01-01 15:00:00"))
    assert result == pd.Timestamp("2024-01-01 15:00:00")


def test_normalize_signal_timestamp_day_level_midnight_without_lookup_raises():
    import pytest
    with pytest.raises(ValueError):
        normalize_signal_timestamp(pd.Timestamp("2024-01-01"), _FakeDayFreq())


def test_signal_live_groups_by_shared_align_params_calls_once_per_group():
    s1, s2, s3 = Strategy(alias="A"), Strategy(alias="B"), Strategy(alias="C")
    configs = {
        s1: StrategyConfig(strategy=s1, active_flow_names=frozenset({"signal_live"}),
                            field_values={FactorSignalModule.signal_freq: "1d"}),
        s2: StrategyConfig(strategy=s2, active_flow_names=frozenset({"signal_live"}),
                            field_values={FactorSignalModule.signal_freq: "1d"}),
        s3: StrategyConfig(strategy=s3, active_flow_names=frozenset({"signal_live"}),
                            field_values={FactorSignalModule.signal_freq: "1h"}),
    }
    account = AccountState(strategy_configs=configs)
    account.current_prices_table = pd.DataFrame({"P1": [1.0, 2.0]}, index=pd.date_range("2024-01-01", periods=2))

    aligned = pd.DataFrame({"P1": [1.0]}, index=[pd.Timestamp("2024-01-01")])
    queue = EventQueue()
    ctx = FlowContext(timestamp=None, event_queue=queue)

    calls = []

    def fake_signal_align(data, freq, **kwargs):
        calls.append(freq)
        return aligned

    with patch("tools.testers.backtest.modules.factor_signal.signal_align", side_effect=fake_signal_align):
        _schedule_signal_live_timestamps(account, ctx)

    assert calls.count("1d") == 1  # shared by s1, s2 -> called once
    assert calls.count("1h") == 1  # s3's own group


def test_signal_precomputed_groups_by_factor_identity():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")

    class _FakeFactor:
        def __init__(self):
            self.calls = 0

        def evaluate(self):
            self.calls += 1
            return pd.DataFrame({"P1": [1.0]}, index=[pd.Timestamp("2024-01-01")])

    shared_factor = _FakeFactor()
    configs = {
        s1: StrategyConfig(strategy=s1, active_flow_names=frozenset({"signal_precomputed"}),
                            field_values={FactorModule.factor: shared_factor}),
        s2: StrategyConfig(strategy=s2, active_flow_names=frozenset({"signal_precomputed"}),
                            field_values={FactorModule.factor: shared_factor}),
    }
    account = AccountState(strategy_configs=configs)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _schedule_signal_precomputed_timestamps(account, ctx)

    assert shared_factor.calls == 1
    assert (id(shared_factor), "factor") in account.precomputed_factor_tables


def test_signal_precomputed_calendar_frequency_aligns_schedule():
    strategy = Strategy(alias="A")

    class _FakeFactor:
        def evaluate(self):
            return pd.DataFrame(
                {"P1": [1.0, 2.0]},
                index=pd.date_range("2024-01-01 09:00", periods=2, freq="min"),
            )

    aligned = pd.DataFrame(
        {"P1": [2.0]},
        index=[pd.Timestamp("2024-01-01 09:01")],
    )
    factor = _FakeFactor()
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"signal_precomputed"}),
        field_values={
            FactorModule.factor: factor,
            FactorSignalModule.calendar_frequency: "5min",
            FactorSignalModule.basepoint: "last",
            FactorSignalModule.end_session_gap: "3h",
        },
    )
    account = AccountState(strategy_configs={strategy: config})
    queue = EventQueue()
    ctx = FlowContext(timestamp=None, event_queue=queue)

    with patch("tools.testers.backtest.modules.factor_signal.signal_align", return_value=aligned) as align:
        _schedule_signal_precomputed_timestamps(account, ctx)

    align.assert_called_once()
    assert align.call_args.args[1] == "5min"
    key = account.precomputed_factor_table_keys[strategy]
    assert key in account.precomputed_factor_tables
    assert list(account.precomputed_factor_tables[key].index) == [pd.Timestamp("2024-01-01 09:01")]


def test_signal_live_observes_bars_then_signals_from_causal_price_table():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")

    class _LiveFactor:
        def __init__(self):
            self.bars = []
            self.evaluate_calls = 0

        def on_bar(self, timestamp, prices):
            self.bars.append((timestamp, prices))

        def on_signal(self, timestamp, price_table):
            self.signal_timestamp = timestamp
            self.signal_table = price_table
            return price_table.iloc[-1]

        def evaluate(self):
            self.evaluate_calls += 1
            raise AssertionError("live factor should not need whole-table evaluate()")

    shared_factor = _LiveFactor()
    configs = {
        s1: StrategyConfig(strategy=s1, field_values={FactorModule.factor: shared_factor}),
        s2: StrategyConfig(strategy=s2, field_values={FactorModule.factor: shared_factor}),
    }
    account = AccountState(strategy_configs=configs)
    prices_ref = FieldRef("current_prices", owner="MarketDataModule")

    bar_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                          active_strategies=frozenset({s1, s2}))
    bar_ctx.set(prices_ref, {"P1": 41.0})
    _observe_signal_live_bar(account, bar_ctx)

    bar_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-02"), event_queue=EventQueue(),
                          active_strategies=frozenset({s1, s2}))
    bar_ctx.set(prices_ref, {"P1": 42.0})
    _observe_signal_live_bar(account, bar_ctx)

    signal_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-02"), event_queue=EventQueue(),
                             active_strategies=frozenset({s1, s2}))

    _evaluate_signal_live(account, signal_ctx)

    assert shared_factor.evaluate_calls == 0
    assert len(shared_factor.bars) == 2
    assert list(shared_factor.signal_table.index) == [
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-01-02"),
    ]
    assert signal_ctx.get_for(FactorSignalModule.signal_value, s1) == {"P1": 42.0}
    assert signal_ctx.get_for(FactorSignalModule.signal_value, s2) == {"P1": 42.0}


def test_signal_live_on_event_keeps_evaluate_fallback_for_table_factors():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")

    class _FakeFactor:
        def __init__(self):
            self.calls = 0

        def evaluate(self):
            self.calls += 1
            return pd.DataFrame({"P1": [42.0]}, index=[pd.Timestamp("2024-01-01")])

    shared_factor = _FakeFactor()
    configs = {
        s1: StrategyConfig(strategy=s1, field_values={FactorModule.factor: shared_factor}),
        s2: StrategyConfig(strategy=s2, field_values={FactorModule.factor: shared_factor}),
    }
    account = AccountState(strategy_configs=configs)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                      active_strategies=frozenset({s1, s2}))

    _evaluate_signal_live(account, ctx)

    assert shared_factor.calls == 1
    assert ctx.get_for(FactorSignalModule.signal_value, s1) == {"P1": 42.0}
    assert ctx.get_for(FactorSignalModule.signal_value, s2) == {"P1": 42.0}


def test_signal_live_compiles_factor_expr_executor_from_bar_events():
    strategy = Strategy(alias="A")
    factor = ColumnRef(DataColumn.CLOSE) + 1.0
    configs = {
        strategy: StrategyConfig(strategy=strategy, field_values={FactorModule.factor: factor}),
    }
    account = AccountState(strategy_configs=configs)
    prices_ref = FieldRef("current_prices", owner="MarketDataModule")

    bar_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                          active_strategies=frozenset({strategy}))
    bar_ctx.set(prices_ref, {"P1": {"CLOSE": 10.0}})
    _observe_signal_live_bar(account, bar_ctx)

    signal_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                             active_strategies=frozenset({strategy}))
    _evaluate_signal_live(account, signal_ctx)

    assert signal_ctx.get_for(FactorSignalModule.signal_value, strategy) == {"P1": 11.0}
