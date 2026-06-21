from __future__ import annotations

import numpy as np
import pandas as pd

from tools.backtest.event_driven.contracts import PortfolioIntent, TargetKind
from tools.backtest.factors.events import FactorSignal
from tools.backtest.strategies.group import QuantileGroupStrategy
from tools.backtest.strategies.allocation import AllocationInput, EqualNotionalAllocator
from tools.backtest.strategies.long_short import QuantileLongShortStrategy
from tools.backtest.strategies.rebalance import OnFactorSignal
from tools.backtest.event_driven.runtime import EventRuntime, EventTopic, ReplayEventSource
from tools.backtest.execution.trading import (
    CashAccounting,
    EqualNotionalSizer,
    Ledger,
    MarketState,
)
from tools.backtest.execution.trading import ProviderContractSizer
from tools.backtest.market_rules import (
    ContractRule,
    RuleFallbackPolicy,
    RuleUsageJournal,
    TemporalRuleProvider,
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
            allocator=EqualNotionalAllocator(),
            allocation_inputs=lambda _, selected: AllocationInput(instruments, selected),
            rebalance_policy=OnFactorSignal(),
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


def test_long_short_is_a_peer_strategy_with_one_portfolio_intent() -> None:
    timestamp = pd.Timestamp("2026-01-01")
    instruments = ("A", "B", "C", "D")
    strategy = QuantileLongShortStrategy(
        factor_alias="factor",
        strategy_id="long-short",
        portfolio_id="long-short:portfolio",
        instruments=instruments,
        group_count=2,
        long_group_number=2,
        short_group_number=1,
        allocator=EqualNotionalAllocator(),
        allocation_inputs=lambda _, selected, gross: AllocationInput(
            instruments, selected, gross_exposure=gross
        ),
        rebalance_policy=OnFactorSignal(),
    )
    runtime = EventRuntime("long-short-run")
    runtime.add_source(ReplayEventSource(
        [timestamp],
        [FactorSignal("factor", {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0})],
        topic=EventTopic.FACTOR_SIGNAL,
    ))
    intents = []
    runtime.subscribe(EventTopic.FACTOR_SIGNAL, strategy.on_factor_signal)
    runtime.subscribe(EventTopic.PORTFOLIO_INTENT, lambda event, _: intents.append(event.payload))
    runtime.run()

    assert len(intents) == 1
    np.testing.assert_allclose(intents[0].values, [-0.25, -0.25, 0.25, 0.25])


def test_contract_multiplier_and_minimum_lot_are_provider_driven() -> None:
    timestamp = pd.Timestamp("2026-01-01")
    market = MarketState()
    market.prices["A"] = 100.0
    usage = RuleUsageJournal()
    sizer = ProviderContractSizer(
        market,
        TemporalRuleProvider({}, latest={"A": ContractRule(10.0, 2.0, 0.2)}),
        RuleFallbackPolicy.LATEST_AVAILABLE,
        usage,
    )
    ledger = Ledger("portfolio", ("A",), 1_000_000, CashAccounting())
    intent = PortfolioIntent(
        timestamp, "strategy", "portfolio", TargetKind.WEIGHT,
        np.array([0.55]), ("A",),
    )

    quantities = sizer.target_quantities(intent, ledger)

    np.testing.assert_array_equal(quantities, [4.0])
    assert usage.approximation_count == 1
