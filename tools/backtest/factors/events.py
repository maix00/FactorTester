"""Factor executors that publish signals into the event runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import pandas as pd

from ..event_driven.runtime import (
    EventDraft,
    EventEnvelope,
    EventRuntime,
    EventTopic,
    MarketSlice,
)


@dataclass(frozen=True, slots=True)
class FactorSignal:
    factor_alias: str
    values: Mapping[str, float]


class PrecomputedFactorPublisher:
    """Expose existing vectorized Factor evaluation as causal signal events."""

    def __init__(self, factor_alias: str, values: pd.DataFrame) -> None:
        if not factor_alias:
            raise ValueError("factor_alias must not be empty")
        if values.empty or not isinstance(values.index, pd.DatetimeIndex):
            raise ValueError("factor values require a non-empty DatetimeIndex")
        if not values.index.is_unique or not values.index.is_monotonic_increasing:
            raise ValueError("factor timestamps must be unique and monotonic")
        if not values.columns.is_unique:
            raise ValueError("factor products must be unique")
        self.factor_alias = factor_alias
        self._values = values

    def on_market_slice(
        self, event: EventEnvelope, runtime: EventRuntime
    ) -> EventDraft:
        market_slice = event.payload
        if not isinstance(market_slice, MarketSlice):
            raise TypeError("market.slice_closed payload must be MarketSlice")
        if event.timestamp not in self._values.index:
            raise KeyError(f"factor {self.factor_alias!r} has no row at {event.timestamp}")
        expected = set(market_slice.prices)
        actual = set(self._values.columns)
        if actual != expected:
            raise ValueError(
                f"factor/market product mismatch: missing={sorted(expected - actual)}, "
                f"extra={sorted(actual - expected)}"
            )
        row = self._values.loc[event.timestamp]
        values = {name: float(row[name]) for name in self._values.columns}
        return EventDraft(
            EventTopic.FACTOR_SIGNAL,
            event.timestamp,
            FactorSignal(self.factor_alias, values),
        )


class IncrementalFactorExecutor:
    """Internal execution target for a compiled stateful FactorExpr graph.

    This is deliberately not an author-facing factor API. Factor authors still
    define one FactorExpr; a future compiler owns construction of this object.
    """

    def __init__(
        self,
        factor_alias: str,
        update: Callable[[pd.Timestamp, MarketSlice], Mapping[str, float] | None],
    ) -> None:
        if not factor_alias or not callable(update):
            raise ValueError("incremental executor requires alias and update callable")
        self.factor_alias = factor_alias
        self._update = update

    def on_market_slice(
        self, event: EventEnvelope, runtime: EventRuntime
    ) -> EventDraft | None:
        market_slice = event.payload
        if not isinstance(market_slice, MarketSlice):
            raise TypeError("market.slice_closed payload must be MarketSlice")
        values = self._update(event.timestamp, market_slice)
        if values is None:
            return None
        normalized = {name: float(value) for name, value in values.items()}
        return EventDraft(
            EventTopic.FACTOR_SIGNAL,
            event.timestamp,
            FactorSignal(self.factor_alias, normalized),
        )
