"""In-memory temporal provider used by database and framework adapters."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from typing import Generic, TypeVar

import pandas as pd

from .contracts import (
    ResolvedRule,
    RuleFallbackPolicy,
    RuleProvenance,
)


T = TypeVar("T")


class MissingMarketRule(LookupError):
    pass


class TemporalRuleProvider(Generic[T]):
    def __init__(
        self,
        history: Mapping[str, Sequence[tuple[pd.Timestamp, T]]],
        *,
        latest: Mapping[str, T] | None = None,
        default: T | None = None,
    ) -> None:
        self.history = {
            instrument: tuple(sorted(
                ((pd.Timestamp(timestamp), value) for timestamp, value in rows),
                key=lambda item: item[0],
            ))
            for instrument, rows in history.items()
        }
        self.latest = dict(latest or {})
        self.default = default

    def resolve(
        self,
        instrument: str,
        timestamp: pd.Timestamp,
        fallback: RuleFallbackPolicy,
    ) -> ResolvedRule[T]:
        timestamp = pd.Timestamp(timestamp)
        rows = self.history.get(instrument, ())
        position = bisect_right([item[0] for item in rows], timestamp) - 1
        if position >= 0:
            effective_at, value = rows[position]
            return ResolvedRule(value, RuleProvenance.EFFECTIVE_AT, effective_at)
        if fallback == RuleFallbackPolicy.LATEST_AVAILABLE and instrument in self.latest:
            return ResolvedRule(
                self.latest[instrument], RuleProvenance.AS_OF_LATEST, None
            )
        if fallback == RuleFallbackPolicy.CONFIGURED_DEFAULT and self.default is not None:
            return ResolvedRule(
                self.default, RuleProvenance.CONFIGURED_DEFAULT, None
            )
        raise MissingMarketRule(
            f"no market rule for {instrument} at {timestamp.isoformat()} "
            f"under {fallback.value}"
        )
