from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tools.backtest.event_driven.contracts import FeeBreakdown, FeeComponent, Order, OrderSide
from tools.backtest.execution.fees import FeeJournal, ProviderCommissionModel
from tools.backtest.event_driven.runtime import EventDraft, EventRuntime, EventTopic
from tools.backtest.execution.trading import CashAccounting, ImmediateBroker, Ledger, MarketState
from tools.backtest.market_rules import (
    FeeSchedule,
    RuleFallbackPolicy,
    RuleUsageJournal,
    TemporalRuleProvider,
)


@dataclass(frozen=True)
class PerContractCommission:
    amount_minor: int

    def calculate(self, order, *, price: float, quantity: float) -> FeeBreakdown:
        return FeeBreakdown((
            FeeComponent("commission", round(quantity * self.amount_minor)),
        ))


def test_commission_is_frozen_on_fill_and_projected_by_ledger() -> None:
    timestamp = pd.Timestamp("2026-01-01 09:01")
    market = MarketState()
    market.prices["A"] = 100.0
    broker = ImmediateBroker(market, PerContractCommission(25))
    ledger = Ledger("portfolio", ("A",), 100_000, CashAccounting())
    runtime = EventRuntime("fee-run")
    runtime.subscribe(EventTopic.ORDER_SUBMITTED, broker.on_order_submitted)
    runtime.subscribe(EventTopic.FILL, ledger.on_fill)
    order = Order(
        order_id="order-1",
        strategy_id="strategy",
        portfolio_id="portfolio",
        timestamp=timestamp,
        instrument="A",
        side=OrderSide.BUY,
        quantity=2.0,
    )

    runtime.publish(EventDraft(EventTopic.ORDER_SUBMITTED, timestamp, order))
    runtime.run()

    assert ledger.fills[0].fees.total_minor == 50
    assert ledger.fee_journal.total_minor == 50
    assert ledger.fee_journal.records[0].fill_id == ledger.fills[0].fill_id
    assert ledger.cash_minor == 79_950


def test_fee_journal_is_a_projection_not_a_calculator() -> None:
    journal = FeeJournal()

    assert journal.records == ()
    assert journal.total_minor == 0


def test_provider_commission_uses_latest_rule_and_records_approximation() -> None:
    timestamp = pd.Timestamp("2026-01-01")
    usage = RuleUsageJournal()
    model = ProviderCommissionModel(
        TemporalRuleProvider({}, latest={"A": FeeSchedule(0.001, 5)}),
        RuleFallbackPolicy.LATEST_AVAILABLE,
        usage,
    )
    order = Order("o", "s", "p", timestamp, "A", OrderSide.BUY, 2.0)

    fees = model.calculate(order, price=100.0, quantity=2.0)

    assert fees.total_minor == 30
    assert usage.approximation_count == 1
