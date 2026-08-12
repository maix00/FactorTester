"""Immutable causal BAR values used by live factor adapters.

An aggregate BAR has two different clocks:

``bar_end``
    The timestamp represented by the observation.
``available_at``
    The simulated time at which the observation is allowed to be read.

Keeping these values separate prevents a visibility delay (or a next-bar
OPEN proxy) from being accidentally treated as the observation timestamp.
The adapter may still expose a pandas table for legacy factors, but the event
boundary is represented by this small immutable value first.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

import pandas as pd


@dataclass(frozen=True, slots=True)
class CausalBar:
    """One visible BAR slice with an explicit information-availability time."""

    bar_end: pd.Timestamp
    available_at: pd.Timestamp
    values: Mapping[Any, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bar_end", pd.Timestamp(self.bar_end))
        object.__setattr__(self, "available_at", pd.Timestamp(self.available_at))
        object.__setattr__(self, "values", _freeze_mapping(self.values))

    def is_visible_at(self, timestamp: pd.Timestamp) -> bool:
        """Return whether this BAR may be consumed at ``timestamp``."""

        return self.available_at <= pd.Timestamp(timestamp)


def _freeze_mapping(value: Mapping[Any, Any]) -> MappingProxyType:
    return MappingProxyType({
        key: _freeze_value(item)
        for key, item in value.items()
    })


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)
    return value


def visible_causal_bars(
    bars: list[CausalBar] | tuple[CausalBar, ...],
    *,
    as_of: pd.Timestamp,
) -> tuple[CausalBar, ...]:
    """Filter and order BARs by availability, never by future row position.

    ``bar_end`` is deliberately not used as the visibility cutoff: a next-bar
    OPEN can be visible before that bar's end timestamp.  The producer must
    supply the correct ``available_at`` for the selected field/basis.
    """

    visible = [bar for bar in bars if bar.is_visible_at(as_of)]
    visible.sort(key=lambda bar: (bar.bar_end, bar.available_at))
    return tuple(visible)
