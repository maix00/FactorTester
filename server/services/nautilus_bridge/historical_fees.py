"""Fill-time Chinese futures commissions using NautilusTrader's FeeModel API.

FactorTester owns the frozen exchange-rule history. NautilusTrader remains the
execution and accounting authority: this model supplies only the commission
for the actual fill. The caller must classify each fill as opening, closing,
or closing today's position from its order/position ledger. An ambiguous fill
is rejected rather than charged at an arbitrary rate.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from typing import Literal

import pandas as pd

from server.services.nautilus_bridge.trading_fields import (
    MARKET_RULE_FIELDS,
    EffectiveRule,
    FrozenTradingFields,
    TradingFieldEvent,
    TradingFieldSource,
    iter_trading_field_timeline,
)
from tools.data.field_history import FieldHistoryProvider

FeeAction = Literal["open", "close", "close_today"]
FEE_FIELDS = (
    "OpenRatioByMoney", "OpenRatioByVolume",
    "CloseRatioByMoney", "CloseRatioByVolume",
    "CloseTodayRatioByMoney", "CloseTodayRatioByVolume",
)


def _event_ns(value: str, timezone: str) -> int:
    at = pd.Timestamp(value)
    if pd.isna(at):
        raise ValueError("fee rule has no effective timestamp")
    if at.tz is None:
        at = at.tz_localize(timezone)
    return int(at.value)


@dataclass(frozen=True, slots=True)
class FeeRuleAt:
    effective_ns: int
    multiplier: Decimal
    rates: tuple[tuple[Decimal, Decimal], tuple[Decimal, Decimal],
                 tuple[Decimal, Decimal]]

    def commission(self, action: FeeAction, quantity: Decimal, price: Decimal) -> Decimal:
        if action not in {"open", "close", "close_today"}:
            raise ValueError(f"unknown fill action {action!r}")
        by_money, by_volume = self.rates[("open", "close", "close_today").index(action)]
        return price * quantity * self.multiplier * by_money + quantity * by_volume


def freeze_fee_schedule(timeline: Iterable[FrozenTradingFields]) -> tuple[FeeRuleAt, ...]:
    """Compress streamed rule snapshots to fee changes without retaining bars."""
    instrument = None
    source = None
    result: list[FeeRuleAt] = []
    previous_fields = None
    previous_ns = None
    for entry in timeline:
        if source is None:
            instrument, source = entry.instrument, entry.source
        if entry.instrument != instrument or entry.source != source:
            raise ValueError("fee timeline mixes contracts or sources")
        effective_ns = _event_ns(entry.timestamp, source.timezone)
        if previous_ns is not None and effective_ns <= previous_ns:
            raise ValueError("fee timeline must be strictly time ordered")
        fields = {field.name: field for field in entry.fields}
        if previous_fields is not None:
            for name in FEE_FIELDS:
                if fields[name].value == previous_fields[name].value:
                    continue
                changed_at = fields[name].effective_timestamp
                if changed_at is None or _event_ns(changed_at, source.timezone) != effective_ns:
                    raise ValueError(
                        f"{name}: fee changed outside an exact replay boundary; "
                        "freeze a rule event at its authoritative effective timestamp"
                    )
        rule = FeeRuleAt(
            effective_ns,
            entry.value("VolumeMultiple"),
            (
                (entry.value("OpenRatioByMoney"), entry.value("OpenRatioByVolume")),
                (entry.value("CloseRatioByMoney"), entry.value("CloseRatioByVolume")),
                (entry.value("CloseTodayRatioByMoney"), entry.value("CloseTodayRatioByVolume")),
            ),
        )
        if result and rule.multiplier != result[0].multiplier:
            raise ValueError("contract multiplier changed within a fee timeline")
        if result and rule.rates == result[-1].rates:
            previous_fields = fields
            previous_ns = effective_ns
            continue
        result.append(rule)
        previous_fields = fields
        previous_ns = effective_ns
    if not result:
        raise ValueError("fee timeline is empty")
    return tuple(result)


def _instrument_product_code(instrument: str) -> str | None:
    """Limit candidate notices; unknown identities conservatively scan all."""
    import re

    parts = instrument.split("|")
    name = parts[2] if len(parts) == 4 and parts[1] == "F" else parts[0]
    match = re.match(r"[A-Za-z]+", name)
    return match.group(0).upper() if match else None


def freeze_fee_schedule_from_history(
    *, source: TradingFieldSource, instrument: str,
    events: Iterable[TradingFieldEvent], provider: FieldHistoryProvider,
    rules: Iterable[EffectiveRule],
) -> tuple[FeeRuleAt, ...]:
    """Resolve only historical rule boundaries, scanning market events once.

    An exact effective timestamp becomes an independent rule event even when
    there is no market bar at that instant. A day-only change still fails
    closed in ``freeze_fee_schedule`` until a session boundary is supplied.
    """
    frame = provider.frame
    candidate_rows = frame[frame["field_name"].isin(MARKET_RULE_FIELDS)]
    product = _instrument_product_code(instrument)
    if product is not None:
        candidate_rows = candidate_rows[
            candidate_rows["instrument"].astype(str).str.upper().isin((product, "*"))
        ]
    boundaries = sorted({
        _event_ns(str(value), source.timezone)
        for value in candidate_rows["effective_timestamp"].dropna()
    })

    def sparse_events():
        previous_ns = None
        previous_day = None
        last_yielded_ns = None
        boundary_index = 0
        for event in events:
            current_ns = _event_ns(str(event.timestamp), source.timezone)
            if previous_ns is not None and current_ns <= previous_ns:
                raise ValueError("market events must be strictly time ordered")
            exact_boundary = False
            while boundary_index < len(boundaries) and boundaries[boundary_index] <= current_ns:
                boundary_ns = boundaries[boundary_index]
                boundary_index += 1
                if boundary_ns == current_ns:
                    exact_boundary = True
                    continue
                if previous_ns is None or boundary_ns <= previous_ns:
                    continue
                boundary = pd.Timestamp(boundary_ns, tz="UTC").tz_convert(source.timezone)
                yield TradingFieldEvent(boundary, event.trading_day)
                last_yielded_ns = boundary_ns
            if (previous_ns is None or event.trading_day != previous_day
                    or exact_boundary):
                yield event
                last_yielded_ns = current_ns
            previous_ns, previous_day = current_ns, event.trading_day
        if previous_ns is not None and last_yielded_ns != previous_ns:
            # Validate the last observed trading day and source coverage.
            yield event

    return freeze_fee_schedule(iter_trading_field_timeline(
        source=source, instrument=instrument, events=sparse_events(),
        provider=provider, rules=rules,
    ))


def make_nautilus_fee_model(
    schedule: tuple[FeeRuleAt, ...], *,
    clock: object,
    currency: str,
):
    """Use the pinned NautilusTrader extension point at the actual fill time.

    NautilusTrader supplies the pre-fill FIFO inventory allocation. Carried inventory is closed
    first; fees are then split across open, close-today and close-yesterday quantities at the
    historical rate effective at the fill timestamp. The adapter does not infer offsets from
    buy/sell direction alone.
    """
    from nautilus_trader.execution import FeeModel
    from nautilus_trader.model import Money

    if not schedule or any(a.effective_ns >= b.effective_ns
                           for a, b in pairwise(schedule)):
        raise ValueError("invalid effective-dated fee schedule")
    if not currency:
        raise ValueError("commission currency is required")
    boundaries = tuple(rule.effective_ns for rule in schedule)

    class HistoricalFeeModel(FeeModel):
        def _rule_at_fill(self):
            now_ns = int(clock.timestamp_ns())
            offset = bisect_right(boundaries, now_ns) - 1
            if offset < 0:
                raise ValueError("no historical fee rule effective at fill time")
            return schedule[offset]

        def get_commission(self, order, fill_quantity, fill_px, instrument):
            rule = self._rule_at_fill()
            amount = rule.commission(
                "open", Decimal(str(fill_quantity)), Decimal(str(fill_px)),
            )
            return Money.from_str(f"{amount} {currency}")

        def get_commission_with_position_context(
            self, order, fill_quantity, fill_px, instrument, underlying_px,
            open_qty, close_today_qty, close_yesterday_qty,
        ):
            rule = self._rule_at_fill()
            price = Decimal(str(fill_px))
            amount = (
                rule.commission("open", Decimal(str(open_qty)), price)
                + rule.commission("close_today", Decimal(str(close_today_qty)), price)
                + rule.commission("close", Decimal(str(close_yesterday_qty)), price)
            )
            return Money.from_str(f"{amount} {currency}")

    return HistoricalFeeModel()
