from __future__ import annotations

import numpy as np
import pandas as pd

from tools.backtest.event_driven.contracts import PortfolioIntent, TargetKind
from tools.backtest.factors.events import FactorSignal
from tools.backtest.strategies.group import QuantileGroupStrategy
from tools.backtest.event_driven.runtime import EventRuntime, EventTopic, ReplayEventSource
from tools.backtest.execution.trading import (
    CashAccounting,
    EqualNotionalSizer,
    Ledger,
    MarketState,
)


def test_five_groups_are_five_independent_strategies() -> None:
    timestamp = pd.Timestamp("2026-01-01")
    instruments = tuple(f"P{index}" for index in range(10))
    signal = FactorSignal(
        "factor-combination-1",
        {instrument: float(index) for index, instrument in enumerate(instruments)},
    )
    runtime = EventRuntime("five-groups")
    runtime.add_source(ReplayEventSource(
        [timestamp], [signal], topic=EventTopic.FACTOR_SIGNAL
    ))
    intents: list[PortfolioIntent] = []
    for group_number in range(1, 6):
        strategy = QuantileGroupStrategy(
            factor_alias="factor-combination-1",
            strategy_id=f"combination-1:group-{group_number}",
            portfolio_id=f"portfolio-{group_number}",
            instruments=instruments,
            group_number=group_number,
            group_count=5,
        )
        runtime.subscribe(EventTopic.FACTOR_SIGNAL, strategy.on_factor_signal)
    runtime.subscribe(
        EventTopic.PORTFOLIO_INTENT,
        lambda event, _: intents.append(event.payload),
    )
    runtime.run()

    assert len(intents) == 5
    assert len({intent.strategy_id for intent in intents}) == 5
    assert len({intent.portfolio_id for intent in intents}) == 5
    for intent in intents:
        assert np.count_nonzero(intent.values) == 2
        assert np.isclose(intent.values.sum(), 1.0)


def test_equal_notional_sizing_is_independent_of_margin_rates() -> None:
    market = MarketState()
    market.prices.update(A=100.0, B=100.0)
    ledger = Ledger("portfolio", ("A", "B"), 10_000_000, CashAccounting())
    sizer = EqualNotionalSizer(
        market,
        point_values={"A": 10.0, "B": 10.0},
        lot_sizes={"A": 1.0, "B": 1.0},
    )
    intent = PortfolioIntent(
        timestamp=pd.Timestamp("2026-01-01"),
        strategy_id="group-1",
        portfolio_id="portfolio",
        target_kind=TargetKind.WEIGHT,
        values=np.array([0.5, 0.5]),
        instruments=("A", "B"),
    )

    quantities = sizer.target_quantities(intent, ledger)

    np.testing.assert_array_equal(quantities, [50.0, 50.0])
