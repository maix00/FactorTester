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
    FactorSignalModule, _evaluate_signal_live, _evaluate_signal_precomputed, _observe_signal_live_bar,
    _schedule_signal_live_timestamps, _schedule_signal_precomputed_timestamps,
    _factor_calculation_key, normalize_signal_timestamp,
)
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.run_window import RunWindowModule


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


def test_factor_calculation_key_separates_market_data_source_and_frequency():
    factor_key = ("factor", "A")
    base = StrategyConfig(
        strategy=Strategy(alias="base"),
        field_values={
            MarketDataModule.data_source_mode: "list",
            MarketDataModule.data_source: ["SRC1"],
            MarketDataModule.freq_mode: "fixed",
            MarketDataModule.freq_fixed: "MIN1",
        },
    )
    different_source = StrategyConfig(
        strategy=Strategy(alias="src"),
        field_values={
            MarketDataModule.data_source_mode: "list",
            MarketDataModule.data_source: ["SRC2"],
            MarketDataModule.freq_mode: "fixed",
            MarketDataModule.freq_fixed: "MIN1",
        },
    )
    different_frequency = StrategyConfig(
        strategy=Strategy(alias="freq"),
        field_values={
            MarketDataModule.data_source_mode: "list",
            MarketDataModule.data_source: ["SRC1"],
            MarketDataModule.freq_mode: "fixed",
            MarketDataModule.freq_fixed: "DAY1",
        },
    )

    assert _factor_calculation_key(factor_key, base) != _factor_calculation_key(factor_key, different_source)
    assert _factor_calculation_key(factor_key, base) != _factor_calculation_key(factor_key, different_frequency)


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
    assert len(account.precomputed_factor_tables) == 1
    expected_key = _factor_calculation_key(("object", id(shared_factor)), configs[s1])
    assert (expected_key, "factor") in account.precomputed_factor_tables


def test_signal_precomputed_splits_shared_factor_by_warmup_window():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")

    class _FakeFactor:
        def __init__(self):
            self.calls: list[pd.Timedelta | None] = []

        def evaluate(self, *, start_dt=None, end_dt=None, warmup_window=None):
            self.calls.append(warmup_window)
            return pd.DataFrame({"P1": [1.0]}, index=[pd.Timestamp("2024-01-02 09:00")])

    shared_factor = _FakeFactor()
    base_fields = {
        FactorModule.factor: shared_factor,
        RunWindowModule.time_precision: "exact",
        RunWindowModule.timezone: "Asia/Shanghai",
        RunWindowModule.start_date: "2024-01-02",
        RunWindowModule.end_date: "2024-01-02",
        RunWindowModule.start_time: "08:00",
        RunWindowModule.end_time: "10:00",
        FactorSignalModule.warmup_mode: "fixed",
    }
    account = AccountState(strategy_configs={
        s1: StrategyConfig(
            strategy=s1,
            active_flow_names=frozenset({"signal_precomputed"}),
            field_values={**base_fields, FactorSignalModule.warmup_window: "1d"},
        ),
        s2: StrategyConfig(
            strategy=s2,
            active_flow_names=frozenset({"signal_precomputed"}),
            field_values={**base_fields, FactorSignalModule.warmup_window: "2d"},
        ),
    })

    _schedule_signal_precomputed_timestamps(account, FlowContext(timestamp=None, event_queue=EventQueue()))

    assert shared_factor.calls == [pd.Timedelta("1D"), pd.Timedelta("2D")]
    assert len(account.precomputed_factor_tables) == 2


def test_signal_precomputed_clips_events_to_strategy_run_window():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")

    class _FakeFactor:
        def __init__(self):
            self.calls = 0

        def evaluate(self):
            self.calls += 1
            return pd.DataFrame(
                {"P1": [1.0, 2.0, 3.0]},
                index=pd.to_datetime([
                    "2024-01-01 09:00",
                    "2024-01-02 09:00",
                    "2024-01-03 09:00",
                ]),
            )

    factor = _FakeFactor()
    base_fields = {
        FactorModule.factor: factor,
        RunWindowModule.time_precision: "exact",
        RunWindowModule.timezone: "Asia/Shanghai",
        RunWindowModule.start_time: "08:00",
        RunWindowModule.end_time: "10:00",
    }
    configs = {
        s1: StrategyConfig(
            strategy=s1,
            active_flow_names=frozenset({"signal_precomputed"}),
            field_values={
                **base_fields,
                RunWindowModule.start_date: "2024-01-01",
                RunWindowModule.end_date: "2024-01-02",
            },
        ),
        s2: StrategyConfig(
            strategy=s2,
            active_flow_names=frozenset({"signal_precomputed"}),
            field_values={
                **base_fields,
                RunWindowModule.start_date: "2024-01-03",
                RunWindowModule.end_date: "2024-01-03",
            },
        ),
    }
    account = AccountState(strategy_configs=configs)
    queue = EventQueue()
    ctx = FlowContext(timestamp=None, event_queue=queue)

    _schedule_signal_precomputed_timestamps(account, ctx)

    seen: list[tuple[pd.Timestamp, Strategy]] = []
    queue.set_dispatcher(
        EventKind.SIGNAL,
        lambda batch: seen.extend((draft.timestamp, draft.strategy) for draft in batch),
    )
    queue.run_until_drained()

    assert factor.calls == 2
    assert len(account.precomputed_factor_tables) == 2
    assert seen == [
        (pd.Timestamp("2024-01-01 09:00"), s1),
        (pd.Timestamp("2024-01-02 09:00"), s1),
        (pd.Timestamp("2024-01-03 09:00"), s2),
    ]


def test_signal_precomputed_merges_equivalent_exact_windows_across_timezones():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")

    class _FakeFactor:
        def __init__(self):
            self.calls = 0

        def evaluate(self, *, start_dt=None, end_dt=None):
            self.calls += 1
            return pd.DataFrame(
                {"P1": [1.0, 2.0]},
                index=pd.DatetimeIndex([
                    pd.Timestamp("2026-01-01 01:00", tz="UTC"),
                    pd.Timestamp("2026-01-31 07:00", tz="UTC"),
                ]),
            )

    factor = _FakeFactor()
    configs = {
        s1: StrategyConfig(
            strategy=s1,
            active_flow_names=frozenset({"signal_precomputed"}),
            field_values={
                FactorModule.factor: factor,
                RunWindowModule.time_precision: "exact",
                RunWindowModule.timezone: "Asia/Shanghai",
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-01-31",
                RunWindowModule.end_time: "15:00",
            },
        ),
        s2: StrategyConfig(
            strategy=s2,
            active_flow_names=frozenset({"signal_precomputed"}),
            field_values={
                FactorModule.factor: factor,
                RunWindowModule.time_precision: "exact",
                RunWindowModule.timezone: "UTC",
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "01:00",
                RunWindowModule.end_date: "2026-01-31",
                RunWindowModule.end_time: "07:00",
            },
        ),
    }
    account = AccountState(strategy_configs=configs)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _schedule_signal_precomputed_timestamps(account, ctx)

    assert factor.calls == 1
    assert len(account.precomputed_factor_tables) == 1


def test_signal_precomputed_splits_factor_evaluate_by_run_window():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")

    class _FakeFactor:
        def __init__(self):
            self.calls: list[tuple[object, object]] = []

        def evaluate(self, *, start_dt=None, end_dt=None):
            self.calls.append((start_dt, end_dt))
            return pd.DataFrame(
                {"P1": [1.0, 2.0, 3.0, 4.0]},
                index=pd.to_datetime([
                    "2024-01-02 09:00",
                    "2024-01-03 09:00",
                    "2024-01-04 09:00",
                    "2024-01-05 09:00",
                ]),
            )

    factor = _FakeFactor()
    base_fields = {
        FactorModule.factor: factor,
        RunWindowModule.time_precision: "exact",
        RunWindowModule.timezone: "Asia/Shanghai",
        RunWindowModule.start_time: "09:00",
        RunWindowModule.end_time: "15:00",
    }
    account = AccountState(strategy_configs={
        s1: StrategyConfig(
            strategy=s1,
            active_flow_names=frozenset({"signal_precomputed"}),
            field_values={**base_fields, RunWindowModule.start_date: "2024-01-02", RunWindowModule.end_date: "2024-01-03"},
        ),
        s2: StrategyConfig(
            strategy=s2,
            active_flow_names=frozenset({"signal_precomputed"}),
            field_values={**base_fields, RunWindowModule.start_date: "2024-01-04", RunWindowModule.end_date: "2024-01-05"},
        ),
    })
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _schedule_signal_precomputed_timestamps(account, ctx)

    assert len(factor.calls) == 2
    start_dt, end_dt = factor.calls[0]
    assert start_dt.ts == pd.Timestamp("2024-01-02 09:00", tz="Asia/Shanghai")
    assert end_dt.ts == pd.Timestamp("2024-01-03 15:00", tz="Asia/Shanghai")
    start_dt, end_dt = factor.calls[1]
    assert start_dt.ts == pd.Timestamp("2024-01-04 09:00", tz="Asia/Shanghai")
    assert end_dt.ts == pd.Timestamp("2024-01-05 15:00", tz="Asia/Shanghai")


def test_fixed_warmup_extends_evaluate_but_is_clipped_before_signal_align():
    strategy = Strategy(alias="A")

    class _FakeFactor:
        def __init__(self):
            self.calls: list[tuple[object, object, object]] = []

        def evaluate(self, *, start_dt=None, end_dt=None, warmup_window=None):
            self.calls.append((start_dt, end_dt, warmup_window))
            return pd.DataFrame(
                {"P1": [0.0, 1.0, 2.0]},
                index=pd.to_datetime([
                    "2024-01-01 09:00",
                    "2024-01-02 09:00",
                    "2024-01-03 09:00",
                ]),
            )

    factor = _FakeFactor()
    account = AccountState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            active_flow_names=frozenset({"signal_precomputed"}),
            field_values={
                FactorModule.factor: factor,
                RunWindowModule.time_precision: "exact",
                RunWindowModule.timezone: "Asia/Shanghai",
                RunWindowModule.start_date: "2024-01-02",
                RunWindowModule.end_date: "2024-01-03",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_time: "15:00",
                FactorSignalModule.warmup_mode: "fixed",
                FactorSignalModule.warmup_window: "1d",
                FactorSignalModule.calendar_frequency: "1min",
            },
        ),
    })
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    aligned = pd.DataFrame(
        {"P1": [1.0, 2.0]},
        index=pd.to_datetime(["2024-01-02 09:00", "2024-01-03 09:00"]),
    )

    with patch("tools.testers.backtest.modules.factor_signal.signal_align", return_value=aligned) as align:
        _schedule_signal_precomputed_timestamps(account, ctx)

    start_dt, end_dt, warmup_window = factor.calls[0]
    assert start_dt.ts == pd.Timestamp("2024-01-02 09:00", tz="Asia/Shanghai")
    assert end_dt.ts == pd.Timestamp("2024-01-03 15:00", tz="Asia/Shanghai")
    assert warmup_window == pd.Timedelta("1D")
    align_input = align.call_args.args[0]
    assert list(align_input.index) == [
        pd.Timestamp("2024-01-02 09:00"),
        pd.Timestamp("2024-01-03 09:00"),
    ]


def test_auto_warmup_infers_nested_time_windows_for_evaluate_warmup():
    strategy = Strategy(alias="A")

    class _FakeFactor:
        _expr = ColumnRef(DataColumn.CLOSE).rolling_mean("2D").shift("1D")

        def __init__(self):
            self.calls: list[tuple[object, object, object]] = []

        def evaluate(self, *, start_dt=None, end_dt=None, warmup_window=None):
            self.calls.append((start_dt, end_dt, warmup_window))
            return pd.DataFrame(
                {"P1": [1.0]},
                index=pd.to_datetime(["2024-01-04 09:00"]),
            )

    factor = _FakeFactor()
    account = AccountState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            active_flow_names=frozenset({"signal_precomputed"}),
            field_values={
                FactorModule.factor: factor,
                RunWindowModule.time_precision: "exact",
                RunWindowModule.timezone: "Asia/Shanghai",
                RunWindowModule.start_date: "2024-01-04",
                RunWindowModule.end_date: "2024-01-04",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_time: "15:00",
                FactorSignalModule.warmup_mode: "auto",
            },
        ),
    })

    _schedule_signal_precomputed_timestamps(account, FlowContext(timestamp=None, event_queue=EventQueue()))

    start_dt, _end_dt, warmup_window = factor.calls[0]
    assert start_dt.ts == pd.Timestamp("2024-01-04 09:00", tz="Asia/Shanghai")
    assert warmup_window == pd.Timedelta("3D")


def test_signal_precomputed_same_window_batches_strategies_by_timestamp():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")

    class _FakeFactor:
        def evaluate(self):
            return pd.DataFrame(
                {"P1": [1.0, 2.0]},
                index=pd.to_datetime(["2024-01-01 09:00", "2024-01-02 09:00"]),
            )

    fields = {
        FactorModule.factor: _FakeFactor(),
        RunWindowModule.time_precision: "exact",
        RunWindowModule.timezone: "Asia/Shanghai",
        RunWindowModule.start_date: "2024-01-01",
        RunWindowModule.end_date: "2024-01-02",
        RunWindowModule.start_time: "08:00",
        RunWindowModule.end_time: "10:00",
    }
    account = AccountState(strategy_configs={
        s1: StrategyConfig(strategy=s1, active_flow_names=frozenset({"signal_precomputed"}), field_values=fields),
        s2: StrategyConfig(strategy=s2, active_flow_names=frozenset({"signal_precomputed"}), field_values=fields),
    })
    queue = EventQueue()
    ctx = FlowContext(timestamp=None, event_queue=queue)

    _schedule_signal_precomputed_timestamps(account, ctx)

    batches: list[tuple[pd.Timestamp, set[Strategy]]] = []
    queue.set_dispatcher(
        EventKind.SIGNAL,
        lambda batch: batches.append((batch[0].timestamp, {draft.strategy for draft in batch})),
    )
    queue.run_until_drained()

    assert len(account.precomputed_factor_tables) == 1
    assert batches == [
        (pd.Timestamp("2024-01-01 09:00"), {s1, s2}),
        (pd.Timestamp("2024-01-02 09:00"), {s1, s2}),
    ]


def test_signal_precomputed_uses_strategy_index_key_inside_same_timestamp_batch():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")

    class _FakeFactor:
        pass

    factor = _FakeFactor()
    configs = {
        s1: StrategyConfig(strategy=s1, active_flow_names=frozenset({"signal_precomputed"}),
                           field_values={FactorModule.factor: factor}),
        s2: StrategyConfig(strategy=s2, active_flow_names=frozenset({"signal_precomputed"}),
                           field_values={FactorModule.factor: factor}),
    }
    account = AccountState(strategy_configs=configs)
    timestamp = pd.Timestamp("2026-03-09 21:00")
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-03-10"), timestamp),
            (pd.Timestamp("2026-03-09"), timestamp),
        ],
        names=["trading_day", "trade_time"],
    )
    table = pd.DataFrame({"P1": [10.0, 20.0]}, index=index)
    key = (("object", id(factor)), "factor", ("unbounded",))
    account.precomputed_factor_tables = {key: table}
    account.precomputed_factor_table_keys = {s1: key, s2: key}
    ctx = FlowContext(
        timestamp=timestamp,
        event_queue=EventQueue(),
        active_strategies=frozenset({s1, s2}),
        drafts_by_strategy={
            s1: [EventDraft(EventKind.SIGNAL, timestamp, s1, index_key=index[0], index_names=index.names)],
            s2: [EventDraft(EventKind.SIGNAL, timestamp, s2, index_key=index[1], index_names=index.names)],
        },
    )

    _evaluate_signal_precomputed(account, ctx)

    assert ctx.get_for(FactorSignalModule.signal_value, s1) == {"P1": 10.0}
    assert ctx.get_for(FactorSignalModule.signal_value, s2) == {"P1": 20.0}


def test_signal_precomputed_groups_by_adapter_cache_key():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")

    class _WrappedFactor:
        def __init__(self):
            self.calls = 0

        def evaluate(self):
            self.calls += 1
            return pd.DataFrame({"P1": [1.0]}, index=[pd.Timestamp("2024-01-01")])

    class _Adapter:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def backtest_factor_cache_key(self):
            return ("adapter", "same-factor", ("P1",))

        def evaluate(self):
            return self.wrapped.evaluate()

    wrapped = _WrappedFactor()
    configs = {
        s1: StrategyConfig(strategy=s1, active_flow_names=frozenset({"signal_precomputed"}),
                            field_values={FactorModule.factor: _Adapter(wrapped)}),
        s2: StrategyConfig(strategy=s2, active_flow_names=frozenset({"signal_precomputed"}),
                            field_values={FactorModule.factor: _Adapter(wrapped)}),
    }
    account = AccountState(strategy_configs=configs)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _schedule_signal_precomputed_timestamps(account, ctx)

    assert wrapped.calls == 1


def test_signal_precomputed_does_not_share_different_adapter_cache_keys():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")

    class _Adapter:
        calls = 0

        def __init__(self, product_name: str):
            self.product_name = product_name

        def backtest_factor_cache_key(self):
            return ("adapter", "same-factor", (self.product_name,))

        def evaluate(self):
            type(self).calls += 1
            return pd.DataFrame({self.product_name: [1.0]}, index=[pd.Timestamp("2024-01-01")])

    configs = {
        s1: StrategyConfig(strategy=s1, active_flow_names=frozenset({"signal_precomputed"}),
                            field_values={FactorModule.factor: _Adapter("P1")}),
        s2: StrategyConfig(strategy=s2, active_flow_names=frozenset({"signal_precomputed"}),
                            field_values={FactorModule.factor: _Adapter("P2")}),
    }
    account = AccountState(strategy_configs=configs)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _schedule_signal_precomputed_timestamps(account, ctx)

    assert _Adapter.calls == 2


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


def test_signal_live_on_event_does_not_call_zero_arg_evaluate_fallback():
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

    assert shared_factor.calls == 0
    assert ctx.get_for(FactorSignalModule.signal_value, s1) == {}
    assert ctx.get_for(FactorSignalModule.signal_value, s2) == {}


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
