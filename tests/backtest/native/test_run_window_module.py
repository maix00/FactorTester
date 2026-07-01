from __future__ import annotations

import pandas as pd

from tools.testers.backtest.engines.native.ledger import BacktestRunState, StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext, FlowRegistry, sort_and_validate
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.engines.native.flow import Phase
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.product_selection import ProductSelectionModule, TermStructureExpandModule
from tools.testers.backtest.modules.run_window import RunWindowModule, _resolve_run_window, auto_warmup_window
from tools.factors.FactorExpr import ColumnRef, DataColumn


def test_resolve_run_window_sets_account_and_market_data_defaults():
    strategy = Strategy(alias="A")

    class _Factor:
        def required_warmup_window(self):
            return "2d"

    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.time_precision: "exact",
                RunWindowModule.timezone: "Asia/Shanghai",
                RunWindowModule.start_date: "2026-01-02",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-01-31",
                RunWindowModule.end_time: "15:00",
                FactorModule.factor: _Factor(),
                FactorSignalModule.warmup_mode: "auto",
            },
        ),
    })
    account.market_data_request = {}
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _resolve_run_window(account, ctx)

    window = account.run_window_store.strategy_windows[strategy]
    assert window.start_dt.ts == pd.Timestamp("2026-01-02 09:00", tz="Asia/Shanghai")
    assert window.end_dt.ts == pd.Timestamp("2026-01-31 15:00", tz="Asia/Shanghai")
    assert window.warmup_window == pd.Timedelta("2D")
    assert account.run_window_store.envelope == (window.start_dt, window.end_dt)
    assert account.market_data_request["start_dt"] == window.start_dt
    assert account.market_data_request["end_dt"] == window.end_dt
    assert "warmup_window" not in account.market_data_request


def test_auto_warmup_unwraps_factor_evaluate_adapter_shape():
    class _Factor:
        _expr = ColumnRef(DataColumn.CLOSE).rolling_mean("2D").shift("1D")

    class _Adapter:
        def __init__(self, factor):
            self._factor = factor

        def required_warmup_window(self):
            return None

    assert auto_warmup_window(_Adapter(_Factor())) == pd.Timedelta("3D")


def test_auto_warmup_uses_longest_parallel_dependency_chain():
    class _Factor:
        _expr = (
            ColumnRef(DataColumn.CLOSE).rolling_mean("2D")
            + ColumnRef(DataColumn.OPEN).rolling_mean("5D")
        )

    assert auto_warmup_window(_Factor()) == pd.Timedelta("5D")


def test_auto_warmup_adds_serial_nested_windows():
    class _Factor:
        _expr = ColumnRef(DataColumn.CLOSE).rolling_mean("2D").shift("1D")

    assert auto_warmup_window(_Factor()) == pd.Timedelta("3D")


def test_run_window_flow_orders_before_product_and_market_data_flows():
    registry = FlowRegistry()
    for module in (RunWindowModule, ProductSelectionModule, TermStructureExpandModule, MarketDataModule):
        for flow in module.flows:
            registry.register_flow(flow)

    groups = sort_and_validate(registry.resolve())
    ordered_names = [flow.name for flow in groups[(Phase.PRE_REPLAY, None)]]

    assert ordered_names.index("resolve_run_window") < ordered_names.index("resolve_product_selection")
    assert ordered_names.index("resolve_run_window") < ordered_names.index("expand_term_structure")
    assert ordered_names.index("resolve_run_window") < ordered_names.index("check_market_data_coverage")
