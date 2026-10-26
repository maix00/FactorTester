"""Event-time gate for bounded FactorExpr calculations driven by completed bars.

The FactorExpr incremental executor owns the arithmetic, including ``where``
and minute ``SignalAlign``.  This adapter owns *when* those results may be
observed.  It deliberately refuses daily SignalAlign until a trading-calendar
close driven compiler exists; a date label is never a publication timestamp.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from server.services.nautilus_bridge.market_data import BarClock
from tools.factors.expr.core import FactorExpr
from tools.factors.expr.streaming.incremental import (
    compile_incremental_factor,
)


@dataclass(frozen=True, slots=True)
class FactorPublication:
    factor_ref: str
    formed_at_ns: int
    available_at_ns: int
    first_executable_at_ns: int
    values: Mapping[Any, float]


class EventTimeFactorStream:
    """One run-scoped, one-update-per-complete-slice FactorExpr publisher.

    Every required product must arrive in the *same completed market slice*.
    This avoids cross-sectional results depending on callback order.  A
    caller must provide the first tradable next-open event separately; NT's
    bar callback alone does not promise next-open execution.
    """

    def __init__(self, *, factor_ref: str, expression: FactorExpr,
                 products: tuple[Any, ...], source_freq: Any,
                 session_calendar: Any = None, event_line: Any = None) -> None:
        if not factor_ref.startswith("factor:v2:"):
            raise ValueError("factor stream needs an immutable frozen factor:v2 ref")
        if not products or len(products) != len(set(products)):
            raise ValueError("products must be a nonempty unique tuple")
        self.factor_ref = factor_ref
        self.products = products
        self._executor = compile_incremental_factor(
            factor_ref, expression, products, source_freq=source_freq,
            session_calendar=session_calendar,
            event_line=event_line,
        )
        self._last_end_ns: int | None = None
        # Keep the previous value while a newly completed slice is still
        # waiting for its declared publication delay.  Never keep the panel.
        self._recent: deque[FactorPublication] = deque(maxlen=2)

    def on_completed_slice(
        self, *, clocks_by_product: Mapping[Any, BarClock],
        fields_by_product: Mapping[Any, Mapping[str, float]],
        first_executable_at_ns: int,
        trading_day: pd.Timestamp | None = None,
    ) -> FactorPublication:
        required = set(self.products)
        if set(clocks_by_product) != required or set(fields_by_product) != required:
            raise ValueError("market slice must contain exactly the frozen product set")
        clocks = tuple(clocks_by_product[p] for p in self.products)
        ends = {clock.interval_end_ns for clock in clocks}
        if len(ends) != 1:
            raise ValueError("cross-product bars have different completed interval ends")
        formed_at_ns = clocks[0].interval_end_ns
        available_at_ns = max(clock.available_at_ns for clock in clocks)
        if self._last_end_ns is not None and formed_at_ns <= self._last_end_ns:
            raise ValueError("market slices must have strictly increasing end times")
        if first_executable_at_ns <= available_at_ns:
            raise ValueError("first executable event must follow factor availability")

        # The engine receives completed bars only.  It retains bounded node
        # state, not a second full market panel.  Update once after all T/TL
        # bars for the same completed time have arrived.
        timestamp = pd.Timestamp(formed_at_ns, unit="ns", tz="UTC")
        self._executor.on_bar(timestamp, fields_by_product,
                              trading_day=trading_day)
        values = dict(self._executor.on_signal(timestamp))
        publication = FactorPublication(
            self.factor_ref, formed_at_ns, available_at_ns,
            first_executable_at_ns, values)
        self._recent.append(publication)
        self._last_end_ns = formed_at_ns
        return publication

    def latest_as_of(self, event_time_ns: int) -> FactorPublication | None:
        """Return only a fully available value, never a future bar's value."""
        return next((pub for pub in reversed(self._recent)
                     if pub.available_at_ns <= event_time_ns), None)

    def tradable_as_of(self, event_time_ns: int) -> FactorPublication | None:
        """Return a signal only at/after its separately proven next opening."""
        return next((pub for pub in reversed(self._recent)
                     if pub.first_executable_at_ns <= event_time_ns), None)


def build_factor_expr_bar_adapter(
    *,
    factor_ref: str,
    expression: FactorExpr,
    products: tuple[Any, ...],
    bar_types_by_product: Mapping[Any, Any],
    source_freq: Any,
    bar_clock: Any,
    factor_fields: Any,
    first_executable_at: Any,
    on_publication: Any,
    trading_day: Any = None,
    session_calendar: Any = None,
    event_line: Any = None,
):
    """Build an NT Strategy which advances FactorExpr only from ``on_bar``.

    This is the factor-to-engine boundary: NautilusTrader owns event ordering
    and invokes the strategy after completed bars; FactorTester owns the
    canonical FactorExpr graph and its bounded incremental arithmetic.  The
    source adapter must explicitly provide clocks, factor fields, and the
    next executable event.  No future OHLC value or pandas market panel is
    read here.

    A cross-sectional factor advances only after every frozen product has
    supplied the same completed interval.  At most one interval's input is
    staged, so memory is O(number of products), independent of run length.
    """
    if set(bar_types_by_product) != set(products):
        raise ValueError("bar types must exactly match the frozen factor products")
    if not callable(bar_clock) or not callable(factor_fields):
        raise TypeError("source bar-clock and factor-field adapters are required")
    if not callable(first_executable_at) or not callable(on_publication):
        raise TypeError("execution-time and publication callbacks are required")

    stream = EventTimeFactorStream(
        factor_ref=factor_ref,
        expression=expression,
        products=products,
        source_freq=source_freq,
        session_calendar=session_calendar,
        event_line=event_line,
    )
    product_by_instrument: dict[str, Any] = {}
    for product, value in bar_types_by_product.items():
        instrument_id = str(value.instrument_id)
        if instrument_id in product_by_instrument:
            raise ValueError(f"duplicate bar instrument id: {instrument_id}")
        product_by_instrument[instrument_id] = product

    class FactorExprBarAdapter:
        def __init__(self) -> None:
            self.subscriptions = list(bar_types_by_product.values())
            self._pending_end_ns: int | None = None
            self._pending_clocks: dict[Any, BarClock] = {}
            self._pending_fields: dict[Any, Mapping[str, float]] = {}

        def on_bar(self, bar: Any) -> None:
            instrument_id = str(bar.bar_type.instrument_id)
            try:
                product = product_by_instrument[instrument_id]
            except KeyError as exc:
                raise ValueError(
                    f"Nautilus delivered an unfrozen factor instrument: {instrument_id}"
                ) from exc

            clock = bar_clock(product, bar)
            end_ns = int(clock.interval_end_ns)
            if self._pending_end_ns is not None and end_ns != self._pending_end_ns:
                missing = set(products) - set(self._pending_clocks)
                if missing:
                    raise ValueError(
                        "Nautilus advanced before a complete cross-sectional slice: "
                        + ", ".join(map(str, sorted(missing, key=str)))
                    )
                self._pending_end_ns = None
                self._pending_clocks.clear()
                self._pending_fields.clear()
            if product in self._pending_clocks:
                raise ValueError(
                    f"duplicate Nautilus bar for {product!r} at {end_ns}"
                )
            if self._pending_end_ns is None:
                self._pending_end_ns = end_ns
            elif end_ns < self._pending_end_ns:
                raise ValueError("Nautilus factor bars moved backwards in event time")

            self._pending_clocks[product] = clock
            self._pending_fields[product] = factor_fields(product, bar)
            if set(self._pending_clocks) != set(products):
                return

            executable_ns = int(first_executable_at(dict(self._pending_clocks)))
            publication = stream.on_completed_slice(
                clocks_by_product=self._pending_clocks,
                fields_by_product=self._pending_fields,
                first_executable_at_ns=executable_ns,
                trading_day=(trading_day(end_ns, dict(self._pending_clocks))
                             if callable(trading_day) else None),
            )
            on_publication(publication)
            self._pending_end_ns = None
            self._pending_clocks.clear()
            self._pending_fields.clear()

    return FactorExprBarAdapter()
