"""Event actors for strategy, order routing, execution, and accounting."""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .contracts import Fill, Order, OrderSide, PortfolioIntent, TargetKind
from .factor_events import FactorSignal
from .runtime import (
    EventDraft,
    EventEnvelope,
    EventRuntime,
    EventTopic,
    ProductPrice,
)


class MarketState:
    """Latest observable prices; it never changes portfolio state."""

    def __init__(self) -> None:
        self.prices: dict[str, float] = {}

    def on_market_data(self, event: EventEnvelope, runtime: EventRuntime) -> None:
        quote = event.payload
        if not isinstance(quote, ProductPrice):
            raise TypeError("market.data payload must be ProductPrice")
        if not np.isfinite(quote.price) or quote.price <= 0:
            raise ValueError(f"invalid market price for {quote.product}: {quote.price}")
        self.prices[quote.product] = float(quote.price)


class SignalStrategy:
    """Translate factor signals into targets without touching orders or state."""

    def __init__(
        self,
        portfolio_id: str,
        instruments: tuple[str, ...],
        target_builder: Callable[[FactorSignal], np.ndarray],
    ) -> None:
        self.portfolio_id = portfolio_id
        self.instruments = instruments
        self._target_builder = target_builder

    def on_factor_signal(
        self, event: EventEnvelope, runtime: EventRuntime
    ) -> EventDraft:
        signal = event.payload
        if not isinstance(signal, FactorSignal):
            raise TypeError("factor.signal payload must be FactorSignal")
        intent = PortfolioIntent(
            timestamp=event.timestamp,
            portfolio_id=self.portfolio_id,
            target_kind=TargetKind.QUANTITY,
            values=self._target_builder(signal),
            instruments=self.instruments,
        )
        return EventDraft(EventTopic.PORTFOLIO_INTENT, event.timestamp, intent)


class FillAccounting(Protocol):
    def cash_delta_minor(self, fill: Fill) -> int: ...


@dataclass(frozen=True, slots=True)
class CashAccounting:
    """Cash-product accounting; futures accounting is a separate implementation."""

    minor_per_major: int = 100
    point_values: Mapping[str, float] | None = None

    def cash_delta_minor(self, fill: Fill) -> int:
        point_value = 1.0
        if self.point_values is not None:
            point_value = self.point_values[fill.instrument]
        notional_minor = round(
            fill.quantity * fill.price * point_value * self.minor_per_major
        )
        if fill.side == OrderSide.BUY:
            return -notional_minor - fill.fee_minor
        return notional_minor - fill.fee_minor


class Ledger:
    """The only actor allowed to mutate cash and positions."""

    def __init__(
        self,
        portfolio_id: str,
        instruments: tuple[str, ...],
        initial_cash_minor: int,
        accounting: FillAccounting,
    ) -> None:
        if initial_cash_minor < 0:
            raise ValueError("initial cash must be non-negative")
        self.portfolio_id = portfolio_id
        self.cash_minor = initial_cash_minor
        self.positions = {instrument: 0.0 for instrument in instruments}
        self.accounting = accounting
        self.fills: list[Fill] = []

    def on_fill(self, event: EventEnvelope, runtime: EventRuntime) -> None:
        fill = event.payload
        if not isinstance(fill, Fill):
            raise TypeError("execution.fill payload must be Fill")
        if fill.portfolio_id != self.portfolio_id:
            return
        sign = 1.0 if fill.side == OrderSide.BUY else -1.0
        self.positions[fill.instrument] += sign * fill.quantity
        self.cash_minor += self.accounting.cash_delta_minor(fill)
        self.fills.append(fill)


class OrderManager:
    """Convert target quantities to delta orders from the authoritative ledger."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self._order_sequence = itertools.count()

    def on_portfolio_intent(
        self, event: EventEnvelope, runtime: EventRuntime
    ) -> list[EventDraft]:
        intent = event.payload
        if not isinstance(intent, PortfolioIntent):
            raise TypeError("portfolio.intent payload must be PortfolioIntent")
        if intent.portfolio_id != self.ledger.portfolio_id:
            return []
        if intent.target_kind != TargetKind.QUANTITY:
            raise ValueError("OrderManager currently requires quantity targets")
        if intent.values.ndim != 1:
            raise ValueError("one OrderManager handles one portfolio")

        drafts: list[EventDraft] = []
        for instrument, target in zip(intent.instruments, intent.values, strict=True):
            delta = float(target) - self.ledger.positions[instrument]
            if np.isclose(delta, 0.0):
                continue
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            order = Order(
                order_id=f"{runtime.run_id}:{next(self._order_sequence)}",
                portfolio_id=intent.portfolio_id,
                timestamp=event.timestamp,
                instrument=instrument,
                side=side,
                quantity=abs(delta),
            )
            drafts.append(EventDraft(EventTopic.ORDER_SUBMITTED, event.timestamp, order))
        return drafts


class ImmediateBroker:
    """Deterministic same-timestamp broker; delayed brokers use future Fill drafts."""

    def __init__(
        self,
        market: MarketState,
        fee_minor: Callable[[Order, float], int] | None = None,
    ) -> None:
        self.market = market
        self._fee_minor = fee_minor or (lambda order, price: 0)
        self._fill_sequence = itertools.count()

    def on_order_submitted(
        self, event: EventEnvelope, runtime: EventRuntime
    ) -> list[EventDraft]:
        order = event.payload
        if not isinstance(order, Order):
            raise TypeError("order.submitted payload must be Order")
        if order.instrument not in self.market.prices:
            return [EventDraft(EventTopic.ORDER_REJECTED, event.timestamp, order)]
        price = self.market.prices[order.instrument]
        fill = Fill(
            fill_id=f"{runtime.run_id}:fill:{next(self._fill_sequence)}",
            order_id=order.order_id,
            portfolio_id=order.portfolio_id,
            timestamp=event.timestamp,
            instrument=order.instrument,
            side=order.side,
            quantity=order.quantity,
            price=price,
            fee_minor=self._fee_minor(order, price),
        )
        return [
            EventDraft(EventTopic.ORDER_ACCEPTED, event.timestamp, order),
            EventDraft(EventTopic.FILL, event.timestamp, fill),
        ]
