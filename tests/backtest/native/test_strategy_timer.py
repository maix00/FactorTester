import pandas as pd

from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.flow import Phase
from tools.testers.backtest.engines.native.scheduler import (
    EventQueue,
    FlowContext,
    FlowRegistry,
    run,
    sort_and_validate,
)
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.strategy_hooks import StrategyRuntime


class TimerActor(Strategy):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.events: list[tuple[str, pd.Timestamp]] = []

    def on_start(self, ctx):
        return ctx.set_time_alert("rebalance", pd.Timestamp("2025-01-01 09:30"))

    def on_timer(self, ctx, event):
        self.events.append((event.name, event.timestamp))


def test_strategy_runtime_routes_timer_from_start_to_on_timer():
    strategy = TimerActor(alias="timer")
    state = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            active_flow_names=frozenset({
                "strategy_runtime_on_start",
                "strategy_runtime_on_timer",
            }),
            field_values={},
        ),
    })
    registry = FlowRegistry()
    for flow in StrategyRuntime.flows:
        registry.register_flow(flow)

    run(state, EventQueue(), registry.resolve())

    assert strategy.events == [
        ("rebalance", pd.Timestamp("2025-01-01 09:30")),
    ]


def test_timer_market_snapshot_is_a_formal_flow_input():
    timestamp = pd.Timestamp("2025-01-01 09:30", tz="Asia/Shanghai")
    product = "P1"
    state = BacktestRunState()
    state.market_data_store.current_prices_table = pd.DataFrame(
        {product: [10.0, 11.0]},
        index=pd.DatetimeIndex([
            pd.Timestamp("2025-01-01 09:00", tz="Asia/Shanghai"),
            pd.Timestamp("2025-01-01 09:45", tz="Asia/Shanghai"),
        ]),
    )
    state.market_data_store.market_price_tables = {
        "close": state.market_data_store.current_prices_table,
    }
    ctx = FlowContext(
        timestamp=timestamp,
        event_queue=EventQueue(),
        event_kind=EventKind.TIMER,
    )

    MarketDataModule.lookup_current_prices_on_timer.compute(state, ctx)

    assert ctx.get(MarketDataModule.current_prices) == {product: 10.0}


def test_timer_snapshot_flow_precedes_strategy_timer_flow():
    registry = FlowRegistry()
    registry.register_flow(MarketDataModule.lookup_current_prices_on_timer)
    registry.register_flow(StrategyRuntime.on_timer)

    groups = sort_and_validate(registry.resolve())
    names = [flow.name for flow in groups[(Phase.PER_EVENT, EventKind.TIMER)]]

    assert names == [
        "lookup_current_prices_on_timer",
        "strategy_runtime_on_timer",
    ]
