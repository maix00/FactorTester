"""Fee calculation seam and the immutable ledger projection of charged fees."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from ..native.contracts import FeeBreakdown, FeeComponent, Fill, Order
from ..market_rules import (
    FeeSchedule,
    RuleFallbackPolicy,
    RuleProvider,
    RuleUsageJournal,
)


class FeeScheduleProvider(Protocol):
    """Load market/account fee rules effective at a particular transaction time."""

    def get_schedule(self, instrument: str, timestamp: pd.Timestamp) -> object: ...


class CommissionModel(Protocol):
    """Calculate fees for one execution using an injected schedule provider."""

    def calculate(
        self,
        order: Order,
        *,
        price: float,
        quantity: float,
    ) -> FeeBreakdown: ...


@dataclass(frozen=True, slots=True)
class ZeroCommissionModel:
    """Explicit no-fee policy for research runs that do not model costs."""

    def calculate(
        self,
        order: Order,
        *,
        price: float,
        quantity: float,
    ) -> FeeBreakdown:
        return FeeBreakdown()


class ProviderCommissionModel:
    def __init__(
        self,
        provider: RuleProvider[FeeSchedule],
        fallback: RuleFallbackPolicy,
        usage: RuleUsageJournal,
        *,
        minor_per_major: int = 100,
    ) -> None:
        self.provider = provider
        self.fallback = fallback
        self.usage = usage
        self.minor_per_major = minor_per_major

    def calculate(
        self, order: Order, *, price: float, quantity: float
    ) -> FeeBreakdown:
        resolved = self.provider.resolve(order.instrument, order.timestamp, self.fallback)
        self.usage.record("fee", order.instrument, order.timestamp, resolved)
        schedule = resolved.value
        notional_minor = round(price * quantity * self.minor_per_major)
        amount = round(notional_minor * schedule.notional_rate)
        amount += round(quantity * schedule.fixed_minor_per_unit)
        return FeeBreakdown((FeeComponent("commission", amount),)) if amount else FeeBreakdown()


@dataclass(frozen=True, slots=True)
class FeeRecord:
    """Ledger projection of the fee facts already frozen on one fill."""

    fill_id: str
    order_id: str
    strategy_id: str
    portfolio_id: str
    timestamp: pd.Timestamp
    instrument: str
    fees: FeeBreakdown

    @classmethod
    def from_fill(cls, fill: Fill) -> FeeRecord:
        return cls(
            fill_id=fill.fill_id,
            order_id=fill.order_id,
            strategy_id=fill.strategy_id,
            portfolio_id=fill.portfolio_id,
            timestamp=fill.timestamp,
            instrument=fill.instrument,
            fees=fill.fees,
        )


class FeeJournal:
    """Append-only fee read model; it does not calculate or mutate fees."""

    def __init__(self) -> None:
        self._records: list[FeeRecord] = []

    @property
    def records(self) -> tuple[FeeRecord, ...]:
        return tuple(self._records)

    @property
    def total_minor(self) -> int:
        return sum(record.fees.total_minor for record in self._records)

    def record(self, fill: Fill) -> None:
        self._records.append(FeeRecord.from_fill(fill))
