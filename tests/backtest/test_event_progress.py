from __future__ import annotations

import numpy as np
import pandas as pd

from tools.testers.backtest.engines.native.backtest import BacktestRunner, ExecutionVenue, StrategyLane
from tools.testers.backtest.engines.native.contracts import BacktestPlan, RunIdentity
from tools.testers.backtest.engines.native.runtime import ProductPrice, ReplayEventSource
from tools.testers.backtest.engines.execution.trading import CashAccounting, ImmediateBroker, Ledger, MarketState, OrderManager
from tools.testers.backtest.engines.factors.events import PrecomputedFactorPublisher
from tools.testers.backtest.engines.strategies.signal import SignalStrategy


def test_native_event_runner_reports_time_slice_progress() -> None:
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    products = ("A",)
    market = MarketState()
    broker = ImmediateBroker(market)
    ledger = Ledger("portfolio", products, 100_000, CashAccounting())
    strategy = SignalStrategy(
        "strategy", "portfolio", "factor", products, lambda signal: np.array([0.0])
    )
    progress = []
    runner = BacktestRunner(
        BacktestPlan(RunIdentity("progress-run"), index, products),
        market_source=ReplayEventSource(index, [ProductPrice("A", 10.0), ProductPrice("A", 11.0)]),
        market=market,
        factors=(PrecomputedFactorPublisher("factor", pd.DataFrame({"A": [1.0, 2.0]}, index=index)),),
        lanes=(StrategyLane(strategy, ledger, OrderManager(ledger)),),
        venues=(ExecutionVenue(frozenset({"portfolio"}), broker.on_order_submitted),),
        progress=progress.append,
    )

    runner.run()

    assert [(item.phase, item.completed, item.total) for item in progress] == [
        ("event_replay", 1, 2),
        ("event_replay", 2, 2),
        ("complete", 2, 2),
    ]
