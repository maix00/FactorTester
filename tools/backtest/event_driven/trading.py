"""Event actors for strategy, order routing, execution, and accounting."""

from __future__ import annotations

import itertools
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .contracts import Fill, Order, OrderSide, PortfolioIntent, TargetKind
from .factor_events import FactorSignal
from .fees import CommissionModel, FeeJournal, ZeroCommissionModel
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
        strategy_id: str,
        portfolio_id: str,
        instruments: tuple[str, ...],
        target_builder: Callable[[FactorSignal], np.ndarray],
    ) -> None:
        if not strategy_id or not portfolio_id:
            raise ValueError("strategy_id and portfolio_id must not be empty")
        self.strategy_id = strategy_id
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
            strategy_id=self.strategy_id,
            portfolio_id=self.portfolio_id,
            target_kind=TargetKind.QUANTITY,
            values=self._target_builder(signal),
            instruments=self.instruments,
        )
        return EventDraft(EventTopic.PORTFOLIO_INTENT, event.timestamp, intent)


@dataclass(frozen=True, slots=True)
class AccountingDelta:
    cash_minor: int = 0
    margin_minor: int = 0
    realized_pnl_minor: int = 0


@dataclass(frozen=True, slots=True)
class SettlementPrices:
    prices: Mapping[str, float]


class FillAccounting(Protocol):
    def process_fill(self, fill: Fill) -> AccountingDelta: ...

    def process_settlement(self, settlement: SettlementPrices) -> AccountingDelta: ...


@dataclass(frozen=True, slots=True)
class CashAccounting:
    """Cash-product accounting; futures accounting is a separate implementation."""

    minor_per_major: int = 100
    point_values: Mapping[str, float] | None = None

    def process_fill(self, fill: Fill) -> AccountingDelta:
        point_value = 1.0
        if self.point_values is not None:
            point_value = self.point_values[fill.instrument]
        notional_minor = round(
            fill.quantity * fill.price * point_value * self.minor_per_major
        )
        if fill.side == OrderSide.BUY:
            return AccountingDelta(cash_minor=-notional_minor - fill.fees.total_minor)
        return AccountingDelta(cash_minor=notional_minor - fill.fees.total_minor)

    def process_settlement(self, settlement: SettlementPrices) -> AccountingDelta:
        return AccountingDelta()


@dataclass(frozen=True, slots=True)
class FuturesContractSpec:
    point_value: float
    margin_ratio: float
    lot_size: float = 1.0

    def __post_init__(self) -> None:
        if self.point_value <= 0 or not 0 < self.margin_ratio <= 1 or self.lot_size <= 0:
            raise ValueError("invalid futures contract specification")


class FuturesLotBook:
    """FIFO lots marked in base-currency minor units per contract."""

    def __init__(self) -> None:
        self._lots: deque[list[float | int]] = deque()

    @property
    def quantity(self) -> float:
        return sum(float(lot[0]) for lot in self._lots)

    def open(self, quantity: float, mark_minor: int) -> None:
        if quantity <= 0 or mark_minor <= 0:
            raise ValueError("lot quantity and mark must be positive")
        self._lots.append([float(quantity), int(mark_minor)])

    def close(self, quantity: float, mark_minor: int, margin_ratio: float) -> tuple[int, int]:
        if quantity <= 0 or quantity > self.quantity + 1e-12:
            raise ValueError("cannot close more futures quantity than is open")
        remaining = float(quantity)
        realized = 0
        released_margin = 0
        while remaining > 1e-12:
            lot_quantity = float(self._lots[0][0])
            lot_mark = int(self._lots[0][1])
            taken = min(lot_quantity, remaining)
            realized += round(taken * (mark_minor - lot_mark))
            released_margin += round(taken * lot_mark * margin_ratio)
            lot_quantity -= taken
            remaining -= taken
            if lot_quantity <= 1e-12:
                self._lots.popleft()
            else:
                self._lots[0][0] = lot_quantity
        return realized, released_margin

    def settle(self, mark_minor: int, margin_ratio: float) -> tuple[int, int]:
        pnl = 0
        margin_delta = 0
        for lot in self._lots:
            quantity = float(lot[0])
            old_mark = int(lot[1])
            pnl += round(quantity * (mark_minor - old_mark))
            margin_delta += round(quantity * (mark_minor - old_mark) * margin_ratio)
            lot[1] = mark_minor
        return pnl, margin_delta


class FuturesAccounting:
    """FIFO futures accounting with margin release and daily settlement."""

    def __init__(
        self,
        specs: Mapping[str, FuturesContractSpec],
        *,
        minor_per_major: int = 100,
    ) -> None:
        self.specs = dict(specs)
        self.minor_per_major = minor_per_major
        self.books = {instrument: FuturesLotBook() for instrument in specs}

    def process_fill(self, fill: Fill) -> AccountingDelta:
        spec = self.specs[fill.instrument]
        self._require_lot_size(fill.quantity, spec.lot_size)
        mark_minor = round(fill.price * spec.point_value * self.minor_per_major)
        book = self.books[fill.instrument]
        if fill.side == OrderSide.BUY:
            margin = round(fill.quantity * mark_minor * spec.margin_ratio)
            book.open(fill.quantity, mark_minor)
            return AccountingDelta(
                cash_minor=-margin - fill.fees.total_minor,
                margin_minor=margin,
            )
        realized, released_margin = book.close(
            fill.quantity, mark_minor, spec.margin_ratio
        )
        return AccountingDelta(
            cash_minor=released_margin + realized - fill.fees.total_minor,
            margin_minor=-released_margin,
            realized_pnl_minor=realized,
        )

    def process_settlement(self, settlement: SettlementPrices) -> AccountingDelta:
        pnl = 0
        margin_delta = 0
        for instrument, price in settlement.prices.items():
            spec = self.specs[instrument]
            mark_minor = round(price * spec.point_value * self.minor_per_major)
            instrument_pnl, instrument_margin_delta = self.books[instrument].settle(
                mark_minor, spec.margin_ratio
            )
            pnl += instrument_pnl
            margin_delta += instrument_margin_delta
        return AccountingDelta(
            cash_minor=pnl - margin_delta,
            margin_minor=margin_delta,
            realized_pnl_minor=pnl,
        )

    @staticmethod
    def _require_lot_size(quantity: float, lot_size: float) -> None:
        lots = quantity / lot_size
        if not np.isclose(lots, round(lots)):
            raise ValueError(f"quantity {quantity} is not a multiple of lot size {lot_size}")


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
        self.margin_minor = 0
        self.realized_pnl_minor = 0
        self.positions = {instrument: 0.0 for instrument in instruments}
        self.accounting = accounting
        self.fills: list[Fill] = []
        self.fee_journal = FeeJournal()

    def on_fill(self, event: EventEnvelope, runtime: EventRuntime) -> None:
        fill = event.payload
        if not isinstance(fill, Fill):
            raise TypeError("execution.fill payload must be Fill")
        if fill.portfolio_id != self.portfolio_id:
            return
        sign = 1.0 if fill.side == OrderSide.BUY else -1.0
        delta = self.accounting.process_fill(fill)
        self.positions[fill.instrument] += sign * fill.quantity
        self.cash_minor += delta.cash_minor
        self.margin_minor += delta.margin_minor
        self.realized_pnl_minor += delta.realized_pnl_minor
        self.fills.append(fill)
        self.fee_journal.record(fill)

    @property
    def equity_minor(self) -> int:
        return self.cash_minor + self.margin_minor

    def on_settlement(self, event: EventEnvelope, runtime: EventRuntime) -> None:
        settlement = event.payload
        if not isinstance(settlement, SettlementPrices):
            raise TypeError("account.settlement payload must be SettlementPrices")
        delta = self.accounting.process_settlement(settlement)
        self.cash_minor += delta.cash_minor
        self.margin_minor += delta.margin_minor
        self.realized_pnl_minor += delta.realized_pnl_minor


class PositionSizer(Protocol):
    def target_quantities(self, intent: PortfolioIntent, ledger: Ledger) -> np.ndarray: ...


class EqualNotionalSizer:
    """Convert target weights to lots without using margin as a weight signal."""

    def __init__(
        self,
        market: MarketState,
        point_values: Mapping[str, float],
        lot_sizes: Mapping[str, float],
        *,
        minor_per_major: int = 100,
    ) -> None:
        self.market = market
        self.point_values = dict(point_values)
        self.lot_sizes = dict(lot_sizes)
        self.minor_per_major = minor_per_major

    def target_quantities(self, intent: PortfolioIntent, ledger: Ledger) -> np.ndarray:
        if intent.target_kind != TargetKind.WEIGHT or intent.values.ndim != 1:
            raise ValueError("EqualNotionalSizer requires one-dimensional target weights")
        gross_weight = float(np.sum(np.abs(intent.values)))
        if gross_weight > 1.0 + 1e-12:
            raise ValueError("target weights exceed gross exposure 1; use an explicit leverage policy")
        equity_major = ledger.equity_minor / self.minor_per_major
        quantities = np.zeros_like(intent.values, dtype=float)
        for index, (instrument, weight) in enumerate(
            zip(intent.instruments, intent.values, strict=True)
        ):
            price = self.market.prices[instrument]
            contract_notional = price * self.point_values[instrument]
            lot_size = self.lot_sizes[instrument]
            raw_quantity = abs(float(weight)) * equity_major / contract_notional
            lots = np.floor(raw_quantity / lot_size + 1e-12)
            quantities[index] = np.sign(weight) * lots * lot_size
        return quantities


class OrderManager:
    """Convert target quantities to delta orders from the authoritative ledger."""

    def __init__(self, ledger: Ledger, position_sizer: PositionSizer | None = None) -> None:
        self.ledger = ledger
        self.position_sizer = position_sizer
        self._order_sequence = itertools.count()

    def on_portfolio_intent(
        self, event: EventEnvelope, runtime: EventRuntime
    ) -> list[EventDraft]:
        intent = event.payload
        if not isinstance(intent, PortfolioIntent):
            raise TypeError("portfolio.intent payload must be PortfolioIntent")
        if intent.portfolio_id != self.ledger.portfolio_id:
            return []
        if intent.values.ndim != 1:
            raise ValueError("one OrderManager handles one portfolio")
        if intent.target_kind == TargetKind.QUANTITY:
            target_quantities = intent.values
        else:
            if self.position_sizer is None:
                raise ValueError("weight intents require an explicit PositionSizer")
            target_quantities = self.position_sizer.target_quantities(intent, self.ledger)

        drafts: list[EventDraft] = []
        for instrument, target in zip(intent.instruments, target_quantities, strict=True):
            delta = float(target) - self.ledger.positions[instrument]
            if np.isclose(delta, 0.0):
                continue
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            order = Order(
                order_id=f"{runtime.run_id}:{next(self._order_sequence)}",
                strategy_id=intent.strategy_id,
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
        commission_model: CommissionModel | None = None,
    ) -> None:
        self.market = market
        self.commission_model = commission_model or ZeroCommissionModel()
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
            strategy_id=order.strategy_id,
            portfolio_id=order.portfolio_id,
            timestamp=event.timestamp,
            instrument=order.instrument,
            side=order.side,
            quantity=order.quantity,
            price=price,
            fees=self.commission_model.calculate(
                order, price=price, quantity=order.quantity
            ),
        )
        return [
            EventDraft(EventTopic.ORDER_ACCEPTED, event.timestamp, order),
            EventDraft(EventTopic.FILL, event.timestamp, fill),
        ]


@dataclass(slots=True)
class _OpenOrder:
    order: Order
    remaining: float


class VolumeParticipationBroker:
    """Stateful partial-fill broker with a shared per-bar capacity budget."""

    def __init__(
        self,
        portfolio_ids: set[str],
        *,
        participation_rate: float,
        volume_field: str = "VOLUME",
        commission_model: CommissionModel | None = None,
        fill_price: Callable[[Order, ProductPrice, float, float], float] | None = None,
    ) -> None:
        if not portfolio_ids or not 0 < participation_rate <= 1:
            raise ValueError("broker requires portfolios and participation within (0, 1]")
        self.portfolio_ids = frozenset(portfolio_ids)
        self.participation_rate = participation_rate
        self.volume_field = volume_field
        self.commission_model = commission_model or ZeroCommissionModel()
        self._fill_price = fill_price or (
            lambda order, quote, quantity, share: quote.price
        )
        self._open_orders: dict[str, _OpenOrder] = {}
        self._quotes: dict[str, ProductPrice] = {}
        self._bar_capacity: dict[str, float] = {}
        self._bar_timestamp: dict[str, object] = {}
        self._fill_sequence = itertools.count()

    @property
    def open_order_count(self) -> int:
        return len(self._open_orders)

    def on_market_data(
        self, event: EventEnvelope, runtime: EventRuntime
    ) -> list[EventDraft]:
        quote = event.payload
        if not isinstance(quote, ProductPrice):
            raise TypeError("market.data payload must be ProductPrice")
        raw_volume = quote.fields.get(self.volume_field)
        if raw_volume is None or not np.isfinite(raw_volume) or raw_volume < 0:
            capacity = 0.0
        else:
            capacity = float(raw_volume) * self.participation_rate
        self._quotes[quote.product] = quote
        self._bar_capacity[quote.product] = capacity
        self._bar_timestamp[quote.product] = event.timestamp
        drafts: list[EventDraft] = []
        for open_order in tuple(self._open_orders.values()):
            if open_order.order.instrument == quote.product:
                drafts.extend(self._fill(open_order, event.timestamp, runtime))
        return drafts

    def on_order_submitted(
        self, event: EventEnvelope, runtime: EventRuntime
    ) -> list[EventDraft] | None:
        order = event.payload
        if not isinstance(order, Order):
            raise TypeError("order.submitted payload must be Order")
        if order.portfolio_id not in self.portfolio_ids:
            return None
        if order.order_id in self._open_orders:
            raise ValueError(f"duplicate order id: {order.order_id}")
        open_order = _OpenOrder(order, order.quantity)
        self._open_orders[order.order_id] = open_order
        drafts = [EventDraft(EventTopic.ORDER_ACCEPTED, event.timestamp, order)]
        if self._bar_timestamp.get(order.instrument) == event.timestamp:
            drafts.extend(self._fill(open_order, event.timestamp, runtime))
        return drafts

    def _fill(
        self,
        open_order: _OpenOrder,
        timestamp,
        runtime: EventRuntime,
    ) -> list[EventDraft]:
        order = open_order.order
        available = self._bar_capacity.get(order.instrument, 0.0)
        quantity = min(open_order.remaining, available)
        if quantity <= 1e-12:
            return []
        quote = self._quotes[order.instrument]
        raw_volume = float(quote.fields[self.volume_field])
        volume_share = quantity / raw_volume if raw_volume > 0 else 0.0
        price = float(self._fill_price(order, quote, quantity, volume_share))
        fill = Fill(
            fill_id=f"{runtime.run_id}:fill:{next(self._fill_sequence)}",
            order_id=order.order_id,
            strategy_id=order.strategy_id,
            portfolio_id=order.portfolio_id,
            timestamp=timestamp,
            instrument=order.instrument,
            side=order.side,
            quantity=quantity,
            price=price,
            fees=self.commission_model.calculate(
                order, price=price, quantity=quantity
            ),
        )
        open_order.remaining -= quantity
        self._bar_capacity[order.instrument] = available - quantity
        if open_order.remaining <= 1e-12:
            del self._open_orders[order.order_id]
        return [EventDraft(EventTopic.FILL, timestamp, fill)]
