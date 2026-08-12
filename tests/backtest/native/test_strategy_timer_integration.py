import pandas as pd

from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowRegistry, run
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.strategy_hooks import StrategyRuntime


def _state(strategy, table):
    state = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            active_flow_names=frozenset({
                "lookup_current_prices_on_timer",
                "strategy_runtime_on_start",
                "strategy_runtime_on_timer",
            }),
            field_values={},
        ),
    })
    state.market_data_store.current_prices_table = table
    state.market_data_store.market_price_tables = {"close": table}
    return state


def _registry():
    registry = FlowRegistry()
    registry.register_flow(MarketDataModule.lookup_current_prices_on_timer)
    registry.register_flow(StrategyRuntime.on_start)
    registry.register_flow(StrategyRuntime.on_timer)
    return registry


def test_timer_hook_receives_causal_prices_through_scheduler():
    class PriceTimerActor(Strategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.prices = None

        def on_start(self, ctx):
            return ctx.set_time_alert(
                "rebalance", pd.Timestamp("2025-01-01 09:30", tz="Asia/Shanghai"),
            )

        def on_timer(self, ctx, event):
            self.prices = dict(ctx.current_prices)

    index = pd.DatetimeIndex([
        pd.Timestamp("2025-01-01 09:00", tz="Asia/Shanghai"),
        pd.Timestamp("2025-01-01 09:45", tz="Asia/Shanghai"),
    ])
    table = pd.DataFrame({"P1": [10.0, 11.0]}, index=index)
    strategy = PriceTimerActor(alias="timer-price")

    run(
        _state(strategy, table), EventQueue(), _registry().resolve(),
        enforce_flow_contract=True,
    )

    assert strategy.prices == {"P1": 10.0}


def test_timer_step_audit_keeps_snapshot_and_hook_as_separate_flows():
    class AuditTimerActor(Strategy):
        def on_start(self, ctx):
            return ctx.set_time_alert(
                "audit", pd.Timestamp("2025-01-01 09:30", tz="Asia/Shanghai"),
            )

    table = pd.DataFrame({"P1": [10.0]}, index=pd.DatetimeIndex([
        pd.Timestamp("2025-01-01 09:00", tz="Asia/Shanghai"),
    ]))
    strategy = AuditTimerActor(alias="timer-audit")
    records = []

    run(
        _state(strategy, table), EventQueue(), _registry().resolve(),
        step_mode=True, step_callback=records.append,
    )

    timer_records = [row for row in records if row.get("event_kind") == "TIMER"]
    assert [row["flow_id"] for row in timer_records] == [
        "lookup_current_prices_on_timer",
        "strategy_runtime_on_timer",
    ]
