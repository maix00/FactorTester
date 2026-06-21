"""Explicit strategy rebalance triggers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd


class RebalancePolicy(Protocol):
    name: str

    def should_rebalance(
        self, timestamp: pd.Timestamp, membership: np.ndarray
    ) -> bool: ...


@dataclass(slots=True)
class OnFactorSignal:
    """Rebalance on every signal emitted at the configured factor frequency."""

    name: str = "on_factor_signal"

    def should_rebalance(self, timestamp: pd.Timestamp, membership: np.ndarray) -> bool:
        return bool(np.any(membership))


@dataclass(slots=True)
class BuyAndHold:
    """Rebalance once at the first non-empty signal."""

    name: str = "buy_and_hold"
    _invested: bool = field(default=False, init=False)

    def should_rebalance(self, timestamp: pd.Timestamp, membership: np.ndarray) -> bool:
        if self._invested or not np.any(membership):
            return False
        self._invested = True
        return True


@dataclass(slots=True)
class MembershipChange:
    """Rebalance only when the selected instrument set changes."""

    name: str = "membership_change"
    _previous: np.ndarray | None = field(default=None, init=False, repr=False)

    def should_rebalance(self, timestamp: pd.Timestamp, membership: np.ndarray) -> bool:
        current = np.asarray(membership, dtype=bool)
        changed = self._previous is None or not np.array_equal(current, self._previous)
        self._previous = current.copy()
        return bool(changed and np.any(current))


@dataclass(slots=True)
class ScheduledRebalance:
    """Rebalance when an injected trading-calendar predicate fires."""

    schedule: Callable[[pd.Timestamp], bool]
    name: str = "scheduled"

    def should_rebalance(self, timestamp: pd.Timestamp, membership: np.ndarray) -> bool:
        return bool(np.any(membership) and self.schedule(pd.Timestamp(timestamp)))
