from __future__ import annotations

import pandas as pd

from tools.testers.backtest.engines.native.ledger import AccountState, StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.modules.bar_events import BarEventModule, _schedule_bar_events
from tools.testers.backtest.modules.factor import FactorModule


def test_bar_events_only_registered_for_live_strategies():
    live = Strategy(alias="live")
    precomputed = Strategy(alias="pre")
    account = AccountState(strategy_configs={
        live: StrategyConfig(strategy=live, active_flow_names=frozenset({"signal_live"})),
        precomputed: StrategyConfig(strategy=precomputed, active_flow_names=frozenset({"signal_precomputed"})),
    })
    account.current_prices_table = pd.DataFrame(
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
    account = AccountState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy, active_flow_names=frozenset({"signal_precomputed"})),
    })
    account.current_prices_table = pd.DataFrame(
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
    account = AccountState(strategy_configs={
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
    account.current_prices_table = pd.DataFrame(
        {"P1": [1.0, 2.0]},
        index=[pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")],
    )
    queue = EventQueue()
    ctx = FlowContext(timestamp=None, event_queue=queue)

    _schedule_bar_events(account, ctx)

    events = ctx.get(BarEventModule.dispatched_bar_events)
    assert len(events) == 2
    assert [event.timestamp for event in events] == list(account.current_prices_table.index)
    assert {event.strategy for event in events} == {first}
    assert queue.pending_count() == 2
