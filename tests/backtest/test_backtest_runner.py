from __future__ import annotations

import numpy as np
import pandas as pd

from tools.backtest.event_driven.backtest import (
    BacktestRunner,
    ExecutionVenue,
    StrategyLane,
)
from tools.backtest.event_driven.contracts import BacktestPlan, RunIdentity
from tools.backtest.factors.events import PrecomputedFactorPublisher
from tools.backtest.event_driven.runtime import ProductPrice, ReplayEventSource
from tools.backtest.execution.trading import (
    CashAccounting,
    ImmediateBroker,
    Ledger,
    MarketState,
    OrderManager,
)
from tools.backtest.strategies.signal import SignalStrategy


def test_runner_wires_shared_data_into_isolated_strategy_ledgers() -> None:
    timestamp = pd.Timestamp("2026-01-01 09:01")
    instruments = ("A", "B")
    plan = BacktestPlan(
        identity=RunIdentity("run-1", user_id="user-1", page_uuid="page-1"),
        timestamps=pd.DatetimeIndex([timestamp]),
        instruments=instruments,
    )
    source = ReplayEventSource(
        [timestamp, timestamp],
        [ProductPrice("A", 100.0), ProductPrice("B", 200.0)],
    )
    factor = PrecomputedFactorPublisher(
        "factor-1",
        pd.DataFrame([[1.0, -1.0]], index=[timestamp], columns=instruments),
    )
    market = MarketState()
    broker = ImmediateBroker(market)
    lanes = (
        make_lane("high", "portfolio-high", instruments, np.array([2.0, 0.0])),
        make_lane("low", "portfolio-low", instruments, np.array([0.0, 1.0])),
    )
    runner = BacktestRunner(
        plan,
        market_source=source,
        market=market,
        factors=(factor,),
        lanes=lanes,
        venues=(ExecutionVenue(broker.on_order_submitted),),
    )

    result = runner.run()

    assert result.identity is plan.identity
    assert result.engine == "native-event-driven"
    assert result.event_count == 13
    assert set(result.portfolios) == {"portfolio-high", "portfolio-low"}
    high = result.portfolios["portfolio-high"]
    low = result.portfolios["portfolio-low"]
    assert high.final_snapshot.positions == {"A": 2.0, "B": 0.0}
    assert low.final_snapshot.positions == {"A": 0.0, "B": 1.0}
    assert high.final_snapshot.cash_minor == 980_000
    assert low.final_snapshot.cash_minor == 980_000
    assert {fill.strategy_id for fill in high.fills + low.fills} == {"high", "low"}
    assert len({fill.order_id for fill in high.fills + low.fills}) == 2
    assert len({fill.fill_id for fill in high.fills + low.fills}) == 2
    assert len(high.snapshots) == len(low.snapshots) == 1
    assert high.final_snapshot.timestamp == timestamp


def test_runner_rejects_duplicate_portfolio_ownership() -> None:
    timestamp = pd.Timestamp("2026-01-01")
    instruments = ("A",)
    plan = BacktestPlan(
        RunIdentity("duplicate-run"),
        pd.DatetimeIndex([timestamp]),
        instruments,
    )
    market = MarketState()
    lanes = (
        make_lane("one", "same", instruments, np.array([1.0])),
        make_lane("two", "same", instruments, np.array([1.0])),
    )

    try:
        BacktestRunner(
            plan,
            market_source=ReplayEventSource([timestamp], [ProductPrice("A", 1.0)]),
            market=market,
            factors=(PrecomputedFactorPublisher(
                "factor",
                pd.DataFrame([[1.0]], index=[timestamp], columns=instruments),
            ),),
            lanes=lanes,
            venues=(ExecutionVenue(ImmediateBroker(market).on_order_submitted),),
        )
    except ValueError as error:
        assert str(error) == "portfolio ids must be unique within a run"
    else:
        raise AssertionError("duplicate portfolio ownership must be rejected")


def make_lane(
    strategy_id: str,
    portfolio_id: str,
    instruments: tuple[str, ...],
    target: np.ndarray,
) -> StrategyLane:
    strategy = SignalStrategy(
        strategy_id,
        portfolio_id,
        instruments,
        lambda signal: target,
    )
    ledger = Ledger(portfolio_id, instruments, 1_000_000, CashAccounting())
    return StrategyLane(strategy, ledger, OrderManager(ledger))
