from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from tools.data.types import DataColumn
from tools.factors.expr import CLOSE, ColumnRef, term_ratio
from tools.products.AdjustableTermStructure import TERM_DAYS_TO_MATURITY_COL, TERM_RANK_COL
from tools.data.types.time_freq import DataFreq
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.fields import FieldRef
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.factor_signal import (
    FactorSignalModule, _evaluate_signal_live, _evaluate_signal_precomputed, _observe_signal_live_bar,
    _schedule_signal_live_timestamps, _schedule_signal_precomputed_timestamps,
    _evaluate_factor_for_strategies, _factor_calculation_key,
    _clip_scheduled_table_to_strategy_window, _clip_signal_table_to_strategy_window,
    _live_bar_trading_day,
    _schedule_table_for_strategy, _factor_fields_by_product,
    normalize_signal_timestamp,
)
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.market_data import _factor_required_columns
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.run_window import RunWindowModule


class _FakeMinuteFreq:
    def is_day_multiple(self) -> bool:
        return False


class _FakeDayFreq:
    def is_day_multiple(self) -> bool:
        return True


def test_live_bar_trading_day_uses_bar_event_day_level_for_night_session():
    strategy = Strategy(alias="night-session")
    draft = EventDraft(
        EventKind.BAR,
        pd.Timestamp("2026-01-01 21:01"),
        strategy,
        index_key=(pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-01 21:01")),
        index_names=("DAY1", "MIN1"),
    )

    class _Context:
        def draft_for(self, candidate):
            assert candidate is strategy
            return draft

        def get(self, *_args):
            raise AssertionError("event DAY1 should win over resolver fallback")

    assert _live_bar_trading_day(
        _Context(), [strategy], pd.Timestamp("2026-01-01 21:01"),
    ) == pd.Timestamp("2026-01-02")


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


def test_external_precomputed_factor_uses_market_signal_schedule() -> None:
    product = object()

    class _ExternalFactor:
        provenance = {"factor_sha256": "abc", "execution": "next_bar"}

        def align_to_market_schedule(self, schedule):
            result = pd.DataFrame({product: [3.0]}, index=schedule.index)
            return result

        def to_run_result(self, table):
            return {"table": table, "provenance": self.provenance}

    strategy = Strategy(alias="external")
    config = StrategyConfig(
        strategy=strategy,
        field_values={
            FactorSignalModule.signal_freq: "1d",
            FactorSignalModule.basepoint: "last",
        },
    )
    state = BacktestRunState(strategy_configs={strategy: config})
    market_index = pd.MultiIndex.from_arrays(
        [
            pd.to_datetime(["2026-01-02"]),
            pd.to_datetime(["2026-01-02 15:00"]),
        ],
        names=["trading_day", "trade_time"],
    )
    state.market_data_store.current_prices_table = pd.DataFrame(
        {product: [100.0]}, index=market_index
    )
    schedule = pd.DataFrame({product: [100.0]}, index=market_index)

    with patch(
        "tools.testers.backtest.modules.factor_signal.signal_align",
        return_value=schedule,
    ) as align:
        result = _schedule_table_for_strategy(
            pd.DataFrame(), config, factor=_ExternalFactor(), state=state,
        )

    assert result.index.equals(market_index)
    assert result.iloc[0, 0] == 3.0
    align.assert_called_once()


def test_factor_signal_store_keeps_external_provenance_per_bound_schedule() -> None:
    from tools.testers.backtest.modules.factor_signal import FactorSignalStore

    strategy = Strategy(alias="external")
    store = FactorSignalStore()
    key = ("external", "schedule")
    run_result = object()
    store.put_precomputed_table(
        key,
        pd.DataFrame({"A": [1.0]}, index=[pd.Timestamp("2026-01-01")]),
        provenance={"factor_sha256": "abc", "execution": "next_bar"},
        run_result=run_result,
    )
    store.bind_precomputed_table(strategy, key)

    assert store.precomputed_provenance_for(strategy) == {
        "factor_sha256": "abc", "execution": "next_bar",
    }
    assert store.precomputed_result_for(strategy) is run_result


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


def test_live_market_data_resolves_exact_factor_column_names():
    factor = (ColumnRef(DataColumn.CLOSE_ADJUSTED) + ColumnRef(DataColumn.VOLUME)) / 2

    assert set(_factor_required_columns(factor)) == {"CLOSE_ADJUSTED", "VOLUME"}


def test_live_factor_compile_receives_strategy_resolved_bar_frequency():
    strategy = Strategy(alias="live-frequency")

    class _Executor:
        def on_bar(self, timestamp, prices) -> None:
            pass

    class _Factor:
        def __init__(self) -> None:
            self.source_freq = None

        def compile_incremental(self, *, factor_alias, products, source_freq):
            self.source_freq = source_freq
            return _Executor()

    factor = _Factor()
    config = StrategyConfig(
        strategy=strategy,
        field_values={FactorModule.factor: factor},
    )
    account = BacktestRunState(strategy_configs={strategy: config})
    account.market_data_store.required_frequency_by_strategy[strategy] = DataFreq.MIN1
    ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-02 09:01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set(MarketDataModule.current_market_snapshot, {
        "close": {"P1": 10.0},
        "CLOSE_ADJUSTED": {"P1": 10.5},
    })

    _observe_signal_live_bar(account, ctx)

    assert factor.source_freq == DataFreq.MIN1


def test_live_factor_fields_keep_canonical_data_column_names_per_product():
    assert _factor_fields_by_product({
        "close": {"P1": 10.0},
        "CLOSE": {"P1": 10.0, "P2": 20.0},
        "CLOSE_ADJUSTED": {"P1": 11.0, "P2": 21.0},
        "VOLUME": {"P1": 100.0, "P2": 200.0},
        "TERM_STRUCTURE": {
            "P1": pd.DataFrame({TERM_RANK_COL: [0], DataColumn.CLOSE.name: [10.0]}),
        },
    }) == {
        "P1": {"CLOSE": 10.0, "CLOSE_ADJUSTED": 11.0, "VOLUME": 100.0},
        "P2": {"CLOSE": 20.0, "CLOSE_ADJUSTED": 21.0, "VOLUME": 200.0},
    }


def test_precomputed_factor_uses_registered_products_and_runtime_window_without_wrapper():
    strategy = Strategy(alias="A")

    class _Selection:
        selection_id = "selection-1"
        products = ("P2", "P1")

    class _Factor:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def evaluate(self, products, *, freq=None, start_dt=None, end_dt=None, warmup_window=None):
            self.calls.append((tuple(products), freq, start_dt, end_dt, warmup_window))
            return pd.DataFrame({"P1": [1.0]}, index=[pd.Timestamp("2024-01-02 09:00")])

    factor = _Factor()
    config = StrategyConfig(
        strategy=strategy,
        field_values={
            FactorModule.factor: factor,
            ProductSelectionModule.product_path_selection: _Selection(),
            RunWindowModule.time_precision: "exact",
            RunWindowModule.timezone: "Asia/Shanghai",
            RunWindowModule.start_date: "2024-01-02",
            RunWindowModule.start_time: "09:00",
            RunWindowModule.end_date: "2024-01-03",
            RunWindowModule.end_time: "15:00",
            FactorSignalModule.warmup_mode: "fixed",
            FactorSignalModule.warmup_window: "2d",
        },
    )
    account = BacktestRunState(strategy_configs={strategy: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({"P1", "P2"}))
    ctx.set_for(MarketDataModule.required_frequency, strategy, DataFreq.DAY1)

    _evaluate_factor_for_strategies(factor, [strategy], account, ctx)

    products, freq, start_dt, end_dt, warmup_window = factor.calls[0]
    assert products == ("P1", "P2")
    assert freq == DataFreq.DAY1
    assert start_dt.ts == pd.Timestamp("2024-01-02 09:00", tz="Asia/Shanghai")
    assert end_dt.ts == pd.Timestamp("2024-01-03 15:00", tz="Asia/Shanghai")
    assert warmup_window == pd.Timedelta("2D")


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
    account = BacktestRunState(strategy_configs=configs)
    account.market_data_store.current_prices_table = pd.DataFrame({"P1": [1.0, 2.0]}, index=pd.date_range("2024-01-01", periods=2))

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


def test_signal_live_maps_daily_schedule_to_trading_day_last_bar_close():
    strategy = Strategy(alias="daily-live-exact")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"signal_live"}),
        field_values={
            FactorSignalModule.signal_freq: "1d",
            RunWindowModule.time_precision: "exact",
            RunWindowModule.timezone: "Asia/Shanghai",
            RunWindowModule.start_date: "2024-01-02",
            RunWindowModule.start_time: "10:12",
            RunWindowModule.end_date: "2024-01-02",
            RunWindowModule.end_time: "10:13",
        },
    )
    account = BacktestRunState(strategy_configs={strategy: config})
    account.market_data_store.daily_signal_close_time = "15:00"
    market_times = pd.DatetimeIndex(
        ["2024-01-01 21:01", "2024-01-02 09:00", "2024-01-02 15:00"],
        tz="Asia/Shanghai",
        name="MIN1",
    )
    account.market_data_store.current_prices_table = pd.DataFrame(
        {"P1": [0.5, 1.0, 2.0]},
        index=market_times,
    )
    daily_signal = pd.DataFrame(
        {"P1": [2.0]},
        index=pd.DatetimeIndex(["2024-01-02"], name="_SIGNAL@DAY1"),
    )
    queue = EventQueue()

    with patch(
        "tools.testers.backtest.modules.factor_signal.signal_align",
        return_value=daily_signal,
    ):
        _schedule_signal_live_timestamps(account, FlowContext(timestamp=None, event_queue=queue))

    scheduled = queue.snapshot_head()
    assert [draft.timestamp for draft in scheduled] == [
        pd.Timestamp("2024-01-02 15:00", tz="Asia/Shanghai")
    ]
    assert config.get(RunWindowModule.time_precision) == "exact"
    assert config.get(RunWindowModule.end_time) == "10:13"


def test_signal_live_rejects_missing_close_on_formal_signal_day():
    strategy = Strategy(alias="daily-missing-close")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"signal_live"}),
        field_values={
            FactorSignalModule.signal_freq: "1d",
            RunWindowModule.time_precision: "exact",
            RunWindowModule.start_date: "2024-01-02",
            RunWindowModule.end_date: "2024-01-02",
        },
    )
    account = BacktestRunState(strategy_configs={strategy: config})
    account.market_data_store.daily_signal_close_time = "15:00"
    account.market_data_store.current_prices_table = pd.DataFrame(
        {"P1": [1.0]},
        index=pd.DatetimeIndex(
            ["2024-01-02 09:00"],
            tz="Asia/Shanghai",
            name="MIN1",
        ),
    )
    daily_signal = pd.DataFrame(
        {"P1": [1.0]},
        index=pd.DatetimeIndex(["2024-01-02"], name="_SIGNAL@DAY1"),
    )

    with patch(
        "tools.testers.backtest.modules.factor_signal.signal_align",
        return_value=daily_signal,
    ), pytest.raises(ValueError, match="2024-01-02.*15:00 close bar"):
        _schedule_signal_live_timestamps(
            account,
            FlowContext(timestamp=None, event_queue=EventQueue()),
        )


def test_exact_window_clips_daily_signal_schedule_by_intraday_event_timestamp():
    strategy = Strategy(alias="daily-exact")
    config = StrategyConfig(
        strategy=strategy,
        field_values={
            RunWindowModule.time_precision: "exact",
            RunWindowModule.timezone: "Asia/Shanghai",
            RunWindowModule.start_date: "2024-01-02",
            RunWindowModule.start_time: "09:00",
            RunWindowModule.end_date: "2024-01-02",
            RunWindowModule.end_time: "15:00",
        },
    )
    trading_days = pd.DatetimeIndex([
        "2024-01-01", "2024-01-02", "2024-01-03",
    ], name="_SIGNAL@DAY1")
    event_times = pd.DatetimeIndex([
        "2024-01-01 15:00", "2024-01-02 15:00", "2024-01-03 15:00",
    ], tz="Asia/Shanghai", name="MIN1")
    table = pd.DataFrame(
        {"P1": [1.0, 2.0, 3.0]},
        index=pd.MultiIndex.from_arrays([trading_days, event_times]),
    )

    clipped = _clip_scheduled_table_to_strategy_window(table, config)

    assert list(clipped["P1"]) == [2.0]
    assert list(clipped.index.get_level_values("MIN1")) == [event_times[1]]

    raw_clipped = _clip_signal_table_to_strategy_window(table, config)

    assert list(raw_clipped["P1"]) == [2.0]


def test_schedule_table_maps_explicit_daily_signal_to_market_event_time():
    strategy = Strategy(alias="daily-exact")
    config = StrategyConfig(
        strategy=strategy,
        field_values={
            RunWindowModule.time_precision: "exact",
            RunWindowModule.timezone: "Asia/Shanghai",
            RunWindowModule.start_date: "2024-01-02",
            RunWindowModule.start_time: "09:00",
            RunWindowModule.end_date: "2024-01-02",
            RunWindowModule.end_time: "15:00",
        },
    )
    account = BacktestRunState(strategy_configs={strategy: config})
    market_times = pd.DatetimeIndex([
        "2024-01-02 09:00",
        "2024-01-02 15:00",
    ], tz="Asia/Shanghai")
    account.market_data_store.current_prices_table = pd.DataFrame({"P1": [1.0, 2.0]}, index=market_times)
    table = pd.DataFrame(
        {"P1": [2.0]},
        index=pd.DatetimeIndex(["2024-01-02"], name="_SIGNAL@DAY1"),
    )

    scheduled = _schedule_table_for_strategy(table, config, account)

    assert list(scheduled.index) == [pd.Timestamp("2024-01-02 15:00", tz="Asia/Shanghai")]


def test_schedule_table_preserves_naive_loaded_market_event_semantics():
    strategy = Strategy(alias="daily-naive-market")
    config = StrategyConfig(
        strategy=strategy,
        field_values={
            RunWindowModule.timezone: "Asia/Shanghai",
        },
    )
    account = BacktestRunState(strategy_configs={strategy: config})
    market_times = pd.DatetimeIndex(["2024-01-01", "2024-01-02"])
    account.market_data_store.current_prices_table = pd.DataFrame(
        {"P1": [1.0, 2.0]},
        index=market_times,
    )
    table = pd.DataFrame({"P1": [1.0]}, index=market_times[:1])

    scheduled = _schedule_table_for_strategy(table, config, account)

    assert list(scheduled.index) == [pd.Timestamp("2024-01-01")]


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
    account = BacktestRunState(strategy_configs=configs)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _schedule_signal_precomputed_timestamps(account, ctx)

    assert shared_factor.calls == 1
    assert len(account.factor_signal_store.precomputed_tables) == 1
    expected_key = _factor_calculation_key(("object", id(shared_factor)), configs[s1])
    assert (expected_key, "factor") in account.factor_signal_store.precomputed_tables


def test_signal_precomputed_evaluates_and_publishes_bound_factor_roles():
    strategy = Strategy(alias="roles")

    class _FakeFactor:
        def __init__(self, value):
            self.value = value
            self.calls = 0

        def evaluate(self):
            self.calls += 1
            return pd.DataFrame({"P1": [self.value]}, index=[pd.Timestamp("2024-01-01")])

    primary = _FakeFactor(1.0)
    entry = _FakeFactor(2.0)
    exit_factor = _FakeFactor(3.0)
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"signal_precomputed"}),
        field_values={
            FactorModule.factor: primary,
            FactorModule.factor_role_bindings: {"entry": entry, "exit": exit_factor},
        },
    )
    account = BacktestRunState(strategy_configs={strategy: config})
    schedule_ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _schedule_signal_precomputed_timestamps(account, schedule_ctx)

    event_ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    _evaluate_signal_precomputed(account, event_ctx)

    assert (primary.calls, entry.calls, exit_factor.calls) == (1, 1, 1)
    assert event_ctx.get_for(FactorSignalModule.signal_value, strategy) == {"P1": 1.0}
    assert event_ctx.get_for(FactorModule.factor_role_values, strategy) == {
        "entry": {"P1": 2.0},
        "exit": {"P1": 3.0},
    }


def test_signal_live_rejects_factor_roles_instead_of_using_primary_silently():
    strategy = Strategy(alias="roles")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"signal_live"}),
        field_values={
            FactorModule.factor: object(),
            FactorModule.factor_role_bindings: {"entry": object()},
        },
    )
    account = BacktestRunState(strategy_configs={strategy: config})

    with pytest.raises(NotImplementedError, match="precomputed"):
        _schedule_signal_live_timestamps(
            account, FlowContext(timestamp=None, event_queue=EventQueue())
        )


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
    account = BacktestRunState(strategy_configs={
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
    assert len(account.factor_signal_store.precomputed_tables) == 2


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
    account = BacktestRunState(strategy_configs=configs)
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
    assert len(account.factor_signal_store.precomputed_tables) == 2
    assert seen == [
        (pd.Timestamp("2024-01-01 09:00", tz="Asia/Shanghai"), s1),
        (pd.Timestamp("2024-01-02 09:00", tz="Asia/Shanghai"), s1),
        (pd.Timestamp("2024-01-03 09:00", tz="Asia/Shanghai"), s2),
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
    account = BacktestRunState(strategy_configs=configs)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _schedule_signal_precomputed_timestamps(account, ctx)

    assert factor.calls == 1
    assert len(account.factor_signal_store.precomputed_tables) == 1


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
    account = BacktestRunState(strategy_configs={
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
    account = BacktestRunState(strategy_configs={
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
    account = BacktestRunState(strategy_configs={
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
    account = BacktestRunState(strategy_configs={
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

    assert len(account.factor_signal_store.precomputed_tables) == 1
    assert batches == [
        (pd.Timestamp("2024-01-01 09:00", tz="Asia/Shanghai"), {s1, s2}),
        (pd.Timestamp("2024-01-02 09:00", tz="Asia/Shanghai"), {s1, s2}),
    ]


def test_signal_precomputed_localizes_naive_subset_timestamps_before_event_queue_push():
    strategy = Strategy(alias="A")

    class _FakeFactor:
        def evaluate(self):
            return pd.DataFrame(
                {"PT.GFE": [1.0], "PD.GFE": [2.0], "SI.GFE": [3.0]},
                index=pd.DatetimeIndex([pd.Timestamp("2026-01-05 09:00")]),
            )

    fields = {
        FactorModule.factor: _FakeFactor(),
        RunWindowModule.time_precision: "exact",
        RunWindowModule.timezone: "Asia/Shanghai",
        RunWindowModule.start_date: "2026-01-05",
        RunWindowModule.end_date: "2026-01-05",
        RunWindowModule.start_time: "08:00",
        RunWindowModule.end_time: "15:00",
    }
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy, active_flow_names=frozenset({"signal_precomputed"}), field_values=fields),
    })
    queue = EventQueue()
    queue.push_event(EventDraft(EventKind.BAR, pd.Timestamp("2026-01-05 09:01", tz="Asia/Shanghai"), strategy))
    ctx = FlowContext(timestamp=None, event_queue=queue)

    _schedule_signal_precomputed_timestamps(account, ctx)

    head = queue.snapshot_head()
    assert all(draft.timestamp.tz is not None for draft in head)


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
    account = BacktestRunState(strategy_configs=configs)
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
    account.factor_signal_store.precomputed_tables = {key: table}
    account.factor_signal_store.precomputed_table_keys = {s1: key, s2: key}
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


def test_signal_precomputed_exact_index_key_uses_cached_row_position(monkeypatch):
    import tools.testers.backtest.modules.factor_signal as factor_signal_module

    strategy = Strategy(alias="cached-index")
    timestamp = pd.Timestamp("2026-03-09 21:00")
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2026-03-09"), timestamp)],
        names=["trading_day", "trade_time"],
    )
    table = pd.DataFrame({"P1": [10.0]}, index=index)
    key = ("cached-index",)
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            active_flow_names=frozenset({"signal_precomputed"}),
        ),
    })
    account.factor_signal_store.precomputed_tables = {key: table}
    account.factor_signal_store.precomputed_table_keys = {strategy: key}
    ctx = FlowContext(
        timestamp=timestamp,
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
        drafts_by_strategy={strategy: [EventDraft(
            EventKind.SIGNAL,
            timestamp,
            strategy,
            index_key=index[0],
            index_names=index.names,
        )]},
    )

    def _unexpected_pandas_lookup(*args, **kwargs):
        raise AssertionError("the immutable index locator should serve this row")

    monkeypatch.setattr(
        factor_signal_module,
        "row_at_index_key",
        _unexpected_pandas_lookup,
    )
    _evaluate_signal_precomputed(account, ctx)

    assert ctx.get_for(FactorSignalModule.signal_value, strategy) == {"P1": 10.0}


def test_signal_precomputed_reuses_row_lookup_for_shared_table_and_index_key(monkeypatch):
    import tools.testers.backtest.modules.factor_signal as factor_signal_module

    s1, s2 = Strategy(alias="A"), Strategy(alias="B")
    timestamp = pd.Timestamp("2026-03-09 21:00")
    table = pd.DataFrame({"P1": [10.0]}, index=[timestamp])
    key = ("shared",)
    account = BacktestRunState(strategy_configs={
        s1: StrategyConfig(strategy=s1, active_flow_names=frozenset({"signal_precomputed"})),
        s2: StrategyConfig(strategy=s2, active_flow_names=frozenset({"signal_precomputed"})),
    })
    account.factor_signal_store.precomputed_tables = {key: table}
    account.factor_signal_store.precomputed_table_keys = {s1: key, s2: key}
    calls = 0
    real_row_at = factor_signal_module.row_at

    def _counting_row_at(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_row_at(*args, **kwargs)

    monkeypatch.setattr(factor_signal_module, "row_at", _counting_row_at)
    ctx = FlowContext(
        timestamp=timestamp,
        event_queue=EventQueue(),
        active_strategies=frozenset({s1, s2}),
    )

    _evaluate_signal_precomputed(account, ctx)

    assert calls == 1
    assert ctx.get_for(FactorSignalModule.signal_value, s1) == {"P1": 10.0}
    assert ctx.get_for(FactorSignalModule.signal_value, s2) == {"P1": 10.0}


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
    account = BacktestRunState(strategy_configs=configs)
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
    account = BacktestRunState(strategy_configs=configs)
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
    account = BacktestRunState(strategy_configs={strategy: config})
    queue = EventQueue()
    ctx = FlowContext(timestamp=None, event_queue=queue)

    with patch("tools.testers.backtest.modules.factor_signal.signal_align", return_value=aligned) as align:
        _schedule_signal_precomputed_timestamps(account, ctx)

    align.assert_called_once()
    assert align.call_args.args[1] == "5min"
    key = account.factor_signal_store.precomputed_table_keys[strategy]
    assert key in account.factor_signal_store.precomputed_tables
    assert list(account.factor_signal_store.precomputed_tables[key].index) == [
        pd.Timestamp("2024-01-01 09:01", tz="Asia/Shanghai")
    ]


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
    account = BacktestRunState(strategy_configs=configs)
    bar_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                          active_strategies=frozenset({s1, s2}))
    bar_ctx.set(MarketDataModule.current_market_snapshot, {
        "close": {"P1": 41.0}, "CLOSE": {"P1": 41.0},
    })
    _observe_signal_live_bar(account, bar_ctx)

    bar_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-02"), event_queue=EventQueue(),
                          active_strategies=frozenset({s1, s2}))
    bar_ctx.set(MarketDataModule.current_market_snapshot, {
        "close": {"P1": 42.0}, "CLOSE": {"P1": 42.0},
    })
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


def test_signal_live_buffers_bars_and_keeps_last_duplicate_timestamp():
    strategy = Strategy(alias="legacy-buffer")

    class _LiveFactor:
        def on_signal(self, timestamp, price_table):
            return price_table.iloc[-1]

    factor = _LiveFactor()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={FactorModule.factor: factor},
        ),
    })
    timestamp = pd.Timestamp("2024-01-01")
    for value in (41.0, 42.0):
        bar_ctx = FlowContext(
            timestamp=timestamp,
            event_queue=EventQueue(),
            active_strategies=frozenset({strategy}),
        )
        bar_ctx.set(MarketDataModule.current_market_snapshot, {
            "close": {"P1": value},
            "CLOSE": {"P1": value},
        })
        _observe_signal_live_bar(account, bar_ctx)

    key = next(iter(account.factor_signal_store.live_price_pending_rows))
    assert key not in account.factor_signal_store.live_price_tables

    signal_ctx = FlowContext(
        timestamp=timestamp,
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    _evaluate_signal_live(account, signal_ctx)

    table = account.factor_signal_store.live_price_tables[key]
    assert len(table) == 1
    assert table.iloc[-1]["P1"] == 42.0
    assert signal_ctx.get_for(FactorSignalModule.signal_value, strategy) == {"P1": 42.0}


def test_signal_live_keeps_bar_end_separate_from_visibility_time():
    strategy = Strategy(alias="causal-times")

    class _LiveFactor:
        def on_signal(self, timestamp, price_table):
            self.table = price_table
            return price_table.iloc[-1]

    factor = _LiveFactor()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={FactorModule.factor: factor},
        ),
    })
    bar_end = pd.Timestamp("2024-01-01 09:02")
    available_at = pd.Timestamp("2024-01-01 09:01:00.000001")
    bar_ctx = FlowContext(
        timestamp=available_at,
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
        drafts_by_strategy={strategy: [EventDraft(
            EventKind.BAR,
            available_at,
            strategy,
            payload={"bar_end": bar_end, "available_at": available_at},
        )]},
    )
    bar_ctx.set(MarketDataModule.current_market_snapshot, {
        "close": {"P1": 41.0}, "CLOSE": {"P1": 41.0},
    })
    _observe_signal_live_bar(account, bar_ctx)

    signal_ctx = FlowContext(
        timestamp=available_at,
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    _evaluate_signal_live(account, signal_ctx)

    assert list(factor.table.index) == [bar_end]


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
    account = BacktestRunState(strategy_configs=configs)
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
    account = BacktestRunState(strategy_configs=configs)
    bar_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                          active_strategies=frozenset({strategy}))
    bar_ctx.set(MarketDataModule.current_market_snapshot, {
        "close": {"P1": 10.0}, "CLOSE": {"P1": 10.0},
    })
    _observe_signal_live_bar(account, bar_ctx)

    assert bar_ctx.get_for(FactorSignalModule.live_factor_state, strategy) == {"P1": 11.0}
    assert account.factor_signal_store.live_price_tables == {}

    signal_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                             active_strategies=frozenset({strategy}))
    _evaluate_signal_live(account, signal_ctx)

    assert signal_ctx.get_for(FactorSignalModule.signal_value, strategy) == {"P1": 11.0}


def test_signal_live_factor_expr_requires_canonical_data_column_snapshot_fields():
    strategy = Strategy(alias="A")
    factor = ColumnRef(DataColumn.CLOSE) + 1.0
    configs = {
        strategy: StrategyConfig(strategy=strategy, field_values={FactorModule.factor: factor}),
    }
    account = BacktestRunState(strategy_configs=configs)
    bar_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                          active_strategies=frozenset({strategy}))
    bar_ctx.set(MarketDataModule.current_market_snapshot, {
        "close": {"P1": 10.0},
    })

    _observe_signal_live_bar(account, bar_ctx)

    assert account.factor_signal_store.live_executors == {}
    assert bar_ctx.get_for(FactorSignalModule.live_factor_state, strategy) is None


def test_signal_live_shared_factor_expr_executor_updates_once_across_strategies():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")
    factor = ColumnRef(DataColumn.CLOSE).rolling_mean(2)
    configs = {
        s1: StrategyConfig(strategy=s1, field_values={FactorModule.factor: factor}),
        s2: StrategyConfig(strategy=s2, field_values={FactorModule.factor: factor}),
    }
    account = BacktestRunState(strategy_configs=configs)

    first_bar = FlowContext(timestamp=pd.Timestamp("2024-01-01 09:00"), event_queue=EventQueue(),
                            active_strategies=frozenset({s1, s2}))
    first_bar.set(MarketDataModule.current_market_snapshot, {
        "close": {"P1": 10.0, "P2": 20.0},
        "CLOSE": {"P1": 10.0, "P2": 20.0},
    })
    _observe_signal_live_bar(account, first_bar)

    second_bar = FlowContext(timestamp=pd.Timestamp("2024-01-01 09:01"), event_queue=EventQueue(),
                             active_strategies=frozenset({s1, s2}))
    second_bar.set(MarketDataModule.current_market_snapshot, {
        "close": {"P1": 12.0, "P2": 18.0},
        "CLOSE": {"P1": 12.0, "P2": 18.0},
    })
    _observe_signal_live_bar(account, second_bar)
    assert account.factor_signal_store.live_price_tables == {}

    signal_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01 09:01"), event_queue=EventQueue(),
                             active_strategies=frozenset({s1, s2}))
    _evaluate_signal_live(account, signal_ctx)

    assert len(account.factor_signal_store.live_executors) == 1
    assert signal_ctx.get_for(FactorSignalModule.signal_value, s1) == {"P1": 11.0, "P2": 19.0}
    assert signal_ctx.get_for(FactorSignalModule.signal_value, s2) == {"P1": 11.0, "P2": 19.0}


def test_signal_live_factor_expr_uses_strategy_products_not_extra_snapshot_products():
    strategy = Strategy(alias="A")
    factor = ColumnRef(DataColumn.CLOSE) + 1.0
    configs = {
        strategy: StrategyConfig(strategy=strategy, field_values={FactorModule.factor: factor}),
    }
    account = BacktestRunState(strategy_configs=configs)
    bar_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                          active_strategies=frozenset({strategy}))
    bar_ctx.set_for(ProductSelectionModule.products, strategy, frozenset({"P1"}))
    bar_ctx.set(MarketDataModule.current_market_snapshot, {
        "close": {"P1": 10.0, "CONTRACT_EXTRA": 99.0},
        "CLOSE": {"P1": 10.0, "CONTRACT_EXTRA": 99.0},
    })

    _observe_signal_live_bar(account, bar_ctx)

    signal_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                             active_strategies=frozenset({strategy}))
    _evaluate_signal_live(account, signal_ctx)

    assert signal_ctx.get_for(FactorSignalModule.signal_value, strategy) == {"P1": 11.0}


def test_signal_live_term_structure_factor_expr_from_bar_events():
    strategy = Strategy(alias="A")
    p1, p2 = "TERM1", "TERM2"
    factor = term_ratio(0, 1, CLOSE)
    configs = {
        strategy: StrategyConfig(strategy=strategy, field_values={FactorModule.factor: factor}),
    }
    account = BacktestRunState(strategy_configs=configs)
    bar_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-02 09:00"), event_queue=EventQueue(),
                          active_strategies=frozenset({strategy}))
    bar_ctx.set_for(ProductSelectionModule.products, strategy, frozenset({p1, p2}))
    bar_ctx.set(MarketDataModule.current_market_snapshot, {
        "close": {p1: 1.0, p2: 1.0},
        "CLOSE": {p1: 1.0, p2: 1.0},
        "TERM_STRUCTURE": {
            p1: pd.DataFrame({
                TERM_RANK_COL: [0, 1],
                TERM_DAYS_TO_MATURITY_COL: [10, 40],
                DataColumn.CLOSE.name: [100.0, 95.0],
            }),
            p2: pd.DataFrame({
                TERM_RANK_COL: [0, 1],
                TERM_DAYS_TO_MATURITY_COL: [10, 40],
                DataColumn.CLOSE.name: [120.0, 90.0],
            }),
        },
    })

    _observe_signal_live_bar(account, bar_ctx)
    signal_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-02 09:00"), event_queue=EventQueue(),
                             active_strategies=frozenset({strategy}))
    _evaluate_signal_live(account, signal_ctx)

    assert signal_ctx.get_for(FactorSignalModule.signal_value, strategy) == {
        p1: 100.0 / 95.0 - 1.0,
        p2: 120.0 / 90.0 - 1.0,
    }


def test_signal_live_term_structure_factor_requires_curve_snapshot():
    strategy = Strategy(alias="A")
    factor = term_ratio(0, 1, CLOSE)
    configs = {
        strategy: StrategyConfig(strategy=strategy, field_values={FactorModule.factor: factor}),
    }
    account = BacktestRunState(strategy_configs=configs)
    bar_ctx = FlowContext(timestamp=pd.Timestamp("2024-01-02 09:00"), event_queue=EventQueue(),
                          active_strategies=frozenset({strategy}))
    bar_ctx.set_for(ProductSelectionModule.products, strategy, frozenset({"TERM1"}))
    bar_ctx.set(MarketDataModule.current_market_snapshot, {
        "close": {"TERM1": 1.0},
        "CLOSE": {"TERM1": 1.0},
    })

    with pytest.raises(KeyError, match="TERM_STRUCTURE snapshot is missing curve"):
        _observe_signal_live_bar(account, bar_ctx)
