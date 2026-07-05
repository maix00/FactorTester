from __future__ import annotations

import pandas as pd

from tools.data.types.time_freq import DataFreq
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.modules.bar_events import (
    BarEventModule,
    _bar_event_drafts_for_strategy,
    _schedule_bar_events,
)
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.run_window import RunWindowModule


def test_bar_events_only_registered_for_live_strategies():
    live = Strategy(alias="live")
    precomputed = Strategy(alias="pre")
    account = BacktestRunState(strategy_configs={
        live: StrategyConfig(strategy=live, active_flow_names=frozenset({"signal_live"})),
        precomputed: StrategyConfig(strategy=precomputed, active_flow_names=frozenset({"signal_precomputed"})),
    })
    account.market_data_store.current_prices_table = pd.DataFrame(
        {"P1": [1.0, 2.0]},
        index=[pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")],
    )
    queue = EventQueue()
    ctx = FlowContext(timestamp=None, event_queue=queue)

    _schedule_bar_events(account, ctx)

    events = ctx.get(BarEventModule.dispatched_bar_events)
    assert [event.kind for event in events] == [EventKind.BAR, EventKind.BAR]
    assert {event.strategy for event in events} == {live}
    assert queue.pending_count() == 2


def test_bar_events_not_registered_when_every_strategy_is_precomputed():
    strategy = Strategy(alias="pre")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy, active_flow_names=frozenset({"signal_precomputed"})),
    })
    account.market_data_store.current_prices_table = pd.DataFrame(
        {"P1": [1.0]},
        index=[pd.Timestamp("2024-01-01")],
    )
    queue = EventQueue()
    ctx = FlowContext(timestamp=None, event_queue=queue)

    _schedule_bar_events(account, ctx)

    assert ctx.get(BarEventModule.dispatched_bar_events) is None
    assert queue.pending_count() == 0


def test_bar_events_deduplicate_strategies_sharing_one_live_factor():
    first = Strategy(alias="first")
    second = Strategy(alias="second")
    shared_factor = object()
    account = BacktestRunState(strategy_configs={
        first: StrategyConfig(
            strategy=first,
            active_flow_names=frozenset({"signal_live"}),
            field_values={FactorModule.factor: shared_factor},
        ),
        second: StrategyConfig(
            strategy=second,
            active_flow_names=frozenset({"signal_live"}),
            field_values={FactorModule.factor: shared_factor},
        ),
    })
    account.market_data_store.current_prices_table = pd.DataFrame(
        {"P1": [1.0, 2.0]},
        index=[pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")],
    )
    queue = EventQueue()
    ctx = FlowContext(timestamp=None, event_queue=queue)

    _schedule_bar_events(account, ctx)

    events = ctx.get(BarEventModule.dispatched_bar_events)
    assert len(events) == 2
    assert [event.timestamp for event in events] == list(account.market_data_store.current_prices_table.index)
    assert {event.strategy for event in events} == {first}
    assert queue.pending_count() == 2


def test_bar_events_register_field_visibility_offsets_at_schedule_time():
    strategy = Strategy(alias="live")
    idx = pd.date_range("2024-01-01 09:01", periods=2, freq="1min")
    table = pd.DataFrame({"P1": [10.0, 20.0]}, index=idx)
    config = StrategyConfig(strategy=strategy, field_values={
        BarEventModule.bar_price_bases: ("open", "close"),
    })

    events = _bar_event_drafts_for_strategy(table, strategy, config)

    assert [(event.timestamp, event.payload["bar_basis"], event.index_key) for event in events] == [
        (idx[0] + pd.Timedelta(0), "close", idx[0]),
        (idx[0] + pd.Timedelta(microseconds=1), "open", idx[1]),
        (idx[1] + pd.Timedelta(0), "close", idx[1]),
    ]


def test_bar_open_visibility_does_not_leak_across_session_gap():
    strategy = Strategy(alias="live")
    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-01-06 14:59", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-06 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-07 09:01", tz="Asia/Shanghai"),
    ])
    table = pd.DataFrame({"P1": [10.0, 20.0, 30.0]}, index=idx)
    config = StrategyConfig(strategy=strategy, field_values={
        BarEventModule.bar_price_bases: ("open",),
        EngineModule.bar_open_visibility_delay: "1us",
    })

    events = _bar_event_drafts_for_strategy(table, strategy, config)

    assert [(event.timestamp, event.payload["bar_basis"], event.index_key) for event in events] == [
        (pd.Timestamp("2026-01-06 14:59:00.000001", tz="Asia/Shanghai"), "open", idx[1]),
        (pd.Timestamp("2026-01-07 09:00:00.000001", tz="Asia/Shanghai"), "open", idx[2]),
    ]


def test_bar_events_use_resolved_market_data_frequency():
    strategy = Strategy(alias="live")
    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-01-06 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-07 09:31", tz="Asia/Shanghai"),
    ])
    table = pd.DataFrame({"P1": [10.0, 20.0]}, index=idx)
    config = StrategyConfig(strategy=strategy, field_values={
        BarEventModule.bar_price_bases: ("open",),
        EngineModule.bar_open_visibility_delay: "1us",
    })

    events = _bar_event_drafts_for_strategy(table, strategy, config, bar_freq=DataFreq("MIN30"))

    assert [(event.timestamp, event.payload["bar_basis"], event.index_key) for event in events] == [
        (pd.Timestamp("2026-01-07 09:01:00.000001", tz="Asia/Shanghai"), "open", idx[1]),
    ]


def test_bar_events_split_shared_factor_by_strategy_warmup_window():
    first = Strategy(alias="first")
    second = Strategy(alias="second")
    shared_factor = object()
    base_fields = {
        FactorModule.factor: shared_factor,
        RunWindowModule.time_precision: "exact",
        RunWindowModule.timezone: "Asia/Shanghai",
        RunWindowModule.start_date: "2024-01-03",
        RunWindowModule.end_date: "2024-01-03",
        RunWindowModule.start_time: "09:00",
        RunWindowModule.end_time: "15:00",
        FactorSignalModule.warmup_mode: "fixed",
    }
    account = BacktestRunState(strategy_configs={
        first: StrategyConfig(
            strategy=first,
            active_flow_names=frozenset({"signal_live"}),
            field_values={**base_fields, FactorSignalModule.warmup_window: "1d"},
        ),
        second: StrategyConfig(
            strategy=second,
            active_flow_names=frozenset({"signal_live"}),
            field_values={**base_fields, FactorSignalModule.warmup_window: "2d"},
        ),
    })
    account.market_data_store.current_prices_table = pd.DataFrame(
        {"P1": [1.0, 2.0, 3.0]},
        index=pd.date_range("2024-01-01 09:00", periods=3, freq="D"),
    )
    queue = EventQueue()
    ctx = FlowContext(timestamp=None, event_queue=queue)

    _schedule_bar_events(account, ctx)

    events = ctx.get(BarEventModule.dispatched_bar_events)
    assert len(events) == 5
    assert [(event.timestamp, event.strategy) for event in events] == [
        (pd.Timestamp("2024-01-02 09:00"), first),
        (pd.Timestamp("2024-01-03 09:00"), first),
        (pd.Timestamp("2024-01-01 09:00"), second),
        (pd.Timestamp("2024-01-02 09:00"), second),
        (pd.Timestamp("2024-01-03 09:00"), second),
    ]
    assert queue.pending_count() == 5


def test_bar_events_warmup_counts_actual_bars_not_calendar_time():
    strategy = Strategy(alias="live")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            active_flow_names=frozenset({"signal_live"}),
            field_values={
                FactorModule.factor: object(),
                RunWindowModule.time_precision: "exact",
                RunWindowModule.timezone: "Asia/Shanghai",
                RunWindowModule.start_date: "2024-01-02",
                RunWindowModule.end_date: "2024-01-02",
                RunWindowModule.start_time: "09:01",
                RunWindowModule.end_time: "09:02",
                FactorSignalModule.warmup_mode: "fixed",
                FactorSignalModule.warmup_window: "2min",
            },
        ),
    })
    account.market_data_store.current_prices_table = pd.DataFrame(
        {"P1": [1.0, 2.0, 3.0, 4.0]},
        index=pd.DatetimeIndex([
            "2024-01-01 14:59",
            "2024-01-01 15:00",
            "2024-01-02 09:01",
            "2024-01-02 09:02",
        ]),
    )
    queue = EventQueue()
    ctx = FlowContext(timestamp=None, event_queue=queue)

    _schedule_bar_events(account, ctx)

    events = ctx.get(BarEventModule.dispatched_bar_events)
    assert [event.timestamp for event in events] == [
        pd.Timestamp("2024-01-01 14:59"),
        pd.Timestamp("2024-01-01 15:00"),
        pd.Timestamp("2024-01-02 09:01"),
        pd.Timestamp("2024-01-02 09:02"),
    ]
