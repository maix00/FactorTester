"""Compact timestamp-ordered storage for vectorized target intents."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tools.testers.backtest.modules.target import (
    TargetWeightIntent,
    target_weight_intent,
)
from tools.testers.backtest.modules.time_index_lookup import IndexEventTime


@dataclass
class PrecomputedIntentAxis:
    """One event axis shared by every strategy compiled from the same signal table."""

    event_times: tuple[IndexEventTime, ...]
    _positions: dict[Any, int] | None = None

    def __len__(self) -> int:
        return len(self.event_times)

    def key_at(self, position: int) -> Any:
        return self.event_times[position].index_key

    def matches(self, position: int, event_key: Any, timestamp: Any) -> bool:
        event_time = self.event_times[position]
        return (
            event_time.index_key == event_key
            or event_time.timestamp == pd.Timestamp(timestamp)
        )

    def position_for(self, key: Any) -> int:
        if self._positions is None:
            positions: dict[Any, int] = {}
            for position, event_time in enumerate(self.event_times):
                positions[event_time.index_key] = position
                positions[event_time.timestamp] = position
            self._positions = positions
        return self._positions[key]


class PrecomputedIntentTimeline(Mapping[Any, TargetWeightIntent]):
    """Materialize only the current intent from a dense weights matrix.

    Event replay consumes rows in timestamp order. Random mapping access remains
    available for step inspection and tests, but never caches per-row intent
    objects or product dictionaries.
    """

    def __init__(
        self,
        axis: PrecomputedIntentAxis,
        columns: tuple[Any, ...],
        values: np.ndarray,
        *,
        reason: str,
    ) -> None:
        if values.ndim != 2 or values.shape != (len(axis), len(columns)):
            raise ValueError("precomputed intent matrix shape does not match its axis")
        self._axis = axis
        self._columns = columns
        self._values = values
        self._reason = str(reason)
        self._cursor = 0

    @classmethod
    def from_frame(
        cls,
        axis: PrecomputedIntentAxis,
        weights: pd.DataFrame,
        *,
        reason: str,
    ) -> "PrecomputedIntentTimeline":
        columns = tuple(weights.columns)
        values = weights.loc[:, list(columns)].fillna(0.0).to_numpy(
            dtype=float,
            copy=False,
        )
        return cls(axis, columns, values, reason=reason)

    @property
    def materialized_intent_count(self) -> int:
        return 0

    def consume(self, event_key: Any, timestamp: Any) -> TargetWeightIntent | None:
        if self._cursor < len(self) and self._axis.matches(
            self._cursor,
            event_key,
            timestamp,
        ):
            position = self._cursor
            self._cursor += 1
            return self._intent_at(position)
        try:
            position = self._axis.position_for(event_key)
        except KeyError:
            try:
                position = self._axis.position_for(pd.Timestamp(timestamp))
            except KeyError:
                return None
        self._cursor = max(self._cursor, position + 1)
        return self._intent_at(position)

    def __getitem__(self, key: Any) -> TargetWeightIntent:
        return self._intent_at(self._axis.position_for(key))

    def __iter__(self) -> Iterator[Any]:
        return (self._axis.key_at(position) for position in range(len(self)))

    def __len__(self) -> int:
        return len(self._axis)

    def _intent_at(self, position: int) -> TargetWeightIntent:
        row = self._values[position]
        payload = {
            self._columns[int(column)]: float(row[int(column)])
            for column in np.flatnonzero(row)
        }
        return target_weight_intent(payload, reason=self._reason)
