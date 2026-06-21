from __future__ import annotations

import pandas as pd

from tools.backtest.event_driven.backtest import BacktestRunner, ExecutionVenue
from tools.backtest.event_driven.contracts import BacktestPlan, RunIdentity
from tools.backtest.event_driven.runtime import ProductPrice, ReplayEventSource
from tools.backtest.execution.trading import ImmediateBroker, MarketState
from tools.backtest.factors.events import PrecomputedFactorPublisher
from tools.backtest.strategies.group_backtest import build_quantile_group_lanes
from tools.backtest.strategies.allocation import AllocationInput, EqualNotionalAllocator
from tools.backtest.strategies.rebalance import OnFactorSignal


def test_five_group_strategies_run_from_factor_signal_through_fills() -> None:
    timestamp = pd.Timestamp("2026-01-01 09:01")
    instruments = tuple(f"P{index}" for index in range(10))
    market = MarketState()
    factor_alias = "factor-combination-1"
    lanes = build_quantile_group_lanes(
        factor_alias=factor_alias,
        strategy_prefix="combination-1",
        instruments=instruments,
        group_count=5,
        market=market,
        initial_cash_minor=100_000,
        point_values={instrument: 1.0 for instrument in instruments},
        lot_sizes={instrument: 1.0 for instrument in instruments},
        allocator_factory=lambda _: EqualNotionalAllocator(),
        allocation_inputs=lambda _, selected: AllocationInput(instruments, selected),
        rebalance_policy_factory=lambda _: OnFactorSignal(),
    )
    source = ReplayEventSource(
        [timestamp] * len(instruments),
        [ProductPrice(instrument, 10.0) for instrument in instruments],
    )
    factor = PrecomputedFactorPublisher(
        factor_alias,
        pd.DataFrame(
            [[float(index) for index in range(len(instruments))]],
            index=[timestamp],
            columns=instruments,
        ),
    )
    broker = ImmediateBroker(market)
    runner = BacktestRunner(
        BacktestPlan(
            RunIdentity("five-group-run"),
            pd.DatetimeIndex([timestamp]),
            instruments,
        ),
        market_source=source,
        market=market,
        factors=(factor,),
        lanes=lanes,
        venues=(ExecutionVenue(broker.on_order_submitted),),
    )

    result = runner.run()

    assert len(result.portfolios) == 5
    for group_index, portfolio in enumerate(result.portfolios.values()):
        selected = {
            instrument
            for instrument, quantity in portfolio.final_snapshot.positions.items()
            if quantity > 0
        }
        assert selected == set(instruments[group_index * 2:(group_index + 1) * 2])
        assert len(portfolio.fills) == 2
        assert {fill.quantity for fill in portfolio.fills} == {50.0}
        assert portfolio.final_snapshot.cash_minor == 0
