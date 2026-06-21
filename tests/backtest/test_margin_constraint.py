from __future__ import annotations

import numpy as np
import pandas as pd

from tools.backtest.event_driven.contracts import PortfolioIntent, TargetKind
from tools.backtest.risk.margin import FuturesMarginConstraint
from tools.backtest.event_driven.runtime import EventRuntime, EventTopic, ReplayEventSource
from tools.backtest.execution.trading import CashAccounting, Ledger


def test_margin_constraint_scales_all_group_weights_proportionally() -> None:
    timestamp = pd.Timestamp("2026-01-01")
    intent = PortfolioIntent(
        timestamp=timestamp,
        strategy_id="group-5",
        portfolio_id="portfolio-5",
        target_kind=TargetKind.WEIGHT,
        values=np.array([0.5, 0.5]),
        instruments=("A", "B"),
    )
    ledger = Ledger("portfolio-5", ("A", "B"), 1_000_000, CashAccounting())
    constraint = FuturesMarginConstraint(
        ledger,
        {"A": 0.10, "B": 0.20},
        collateral_fraction=0.10,
    )
    approved: list[PortfolioIntent] = []
    runtime = EventRuntime("margin-scale")
    runtime.add_source(ReplayEventSource(
        [timestamp], [intent], topic=EventTopic.PORTFOLIO_INTENT
    ))
    runtime.subscribe(EventTopic.PORTFOLIO_INTENT, constraint.on_portfolio_intent)
    runtime.subscribe(
        EventTopic.PORTFOLIO_APPROVED,
        lambda event, _: approved.append(event.payload),
    )
    runtime.run()

    assert len(approved) == 1
    np.testing.assert_allclose(approved[0].values, [1 / 3, 1 / 3])
    np.testing.assert_allclose(
        approved[0].values[0] / approved[0].values[1],
        intent.values[0] / intent.values[1],
    )


def test_margin_constraint_can_reject_whole_rebalance() -> None:
    timestamp = pd.Timestamp("2026-01-01")
    intent = PortfolioIntent(
        timestamp=timestamp,
        strategy_id="group-1",
        portfolio_id="portfolio-1",
        target_kind=TargetKind.WEIGHT,
        values=np.array([1.0]),
        instruments=("A",),
    )
    ledger = Ledger("portfolio-1", ("A",), 1_000_000, CashAccounting())
    constraint = FuturesMarginConstraint(
        ledger,
        {"A": 0.20},
        collateral_fraction=0.10,
        reject_instead_of_scale=True,
    )
    rejected = []
    runtime = EventRuntime("margin-reject")
    runtime.add_source(ReplayEventSource(
        [timestamp], [intent], topic=EventTopic.PORTFOLIO_INTENT
    ))
    runtime.subscribe(EventTopic.PORTFOLIO_INTENT, constraint.on_portfolio_intent)
    runtime.subscribe(
        EventTopic.PORTFOLIO_REJECTED,
        lambda event, _: rejected.append(event.payload),
    )
    runtime.run()

    assert rejected == [intent]
