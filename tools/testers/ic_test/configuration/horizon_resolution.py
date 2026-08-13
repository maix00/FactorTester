"""Resolved physical horizons with their authoring provenance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

from tools.data.types import DataFreq


_SCALE_AWARE_MULTIPLIERS = {
    "minute": (1, 2, 3, 5, 10, 15, 30, 60, 120, 240, 480),
    "intraday": (1, 2, 3, 5, 10, 15, 30, 60),
    "daily": (1, 2, 3, 5, 10, 20),
    "slow": (1, 2, 3, 5, 10),
}


@dataclass(frozen=True, slots=True)
class ICHorizonOrigin:
    base: str
    multiplier: int

    def __post_init__(self) -> None:
        if not str(self.base or "").strip():
            raise ValueError("horizon origin base must be non-empty")
        if isinstance(self.multiplier, bool) or self.multiplier < 1:
            raise ValueError("horizon origin multiplier must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {"base": self.base, "multiplier": self.multiplier}

    @classmethod
    def from_dict(cls, value: Any) -> ICHorizonOrigin:
        if not isinstance(value, dict):
            raise ValueError("horizon origin must be an object")
        return cls(str(value.get("base") or ""), value.get("multiplier"))


@dataclass(frozen=True, slots=True)
class ResolvedICHorizon:
    physical_frequency: str
    origins: tuple[ICHorizonOrigin, ...]

    def __post_init__(self) -> None:
        frequency = DataFreq(self.physical_frequency).name
        if not self.origins or len(self.origins) != len(set(self.origins)):
            raise ValueError("resolved horizon requires unique authoring origins")
        object.__setattr__(self, "physical_frequency", frequency)

    def to_dict(self) -> dict[str, Any]:
        return {
            "physical_frequency": self.physical_frequency,
            "origins": [origin.to_dict() for origin in self.origins],
        }

    @classmethod
    def from_dict(cls, value: Any) -> ResolvedICHorizon:
        if not isinstance(value, dict) or not isinstance(value.get("origins"), list):
            raise ValueError("resolved horizon must contain an origins list")
        return cls(
            str(value.get("physical_frequency") or ""),
            tuple(ICHorizonOrigin.from_dict(item) for item in value["origins"]),
        )


def resolve_horizon_entries(
    mode: str,
    bases: Iterable[str],
    multipliers: Iterable[int],
    signal_frequency: Any | None,
) -> tuple[ResolvedICHorizon, ...]:
    signal = DataFreq(signal_frequency) if signal_frequency else None
    if mode == "scale_aware":
        if signal is None or signal.value <= pd.Timedelta(0):
            raise ValueError("scale-aware horizon requires a signal frequency")
        requests = _scale_aware_requests(signal)
    else:
        requests = _explicit_requests(tuple(bases), tuple(multipliers), signal)
    return _merge_requests(requests)


def _explicit_requests(bases, multipliers, signal):
    requests = []
    for base in bases:
        if base == "signal":
            if signal is None or signal.value <= pd.Timedelta(0):
                raise ValueError("signal-relative horizon requires a signal frequency")
            frequency = signal
            origin_base = "signal"
        else:
            frequency = DataFreq(base)
            origin_base = frequency.name
        requests.extend(
            (frequency.value * multiple, ICHorizonOrigin(origin_base, multiple))
            for multiple in multipliers
        )
    return requests


def _scale_aware_requests(signal: DataFreq):
    seconds = float(signal.value.total_seconds())
    if seconds <= 300:
        key = "minute"
    elif seconds < 86400:
        key = "intraday"
    elif seconds == 86400:
        key = "daily"
    else:
        key = "slow"
    requests = [
        (signal.value * multiple, ICHorizonOrigin("signal", multiple))
        for multiple in _SCALE_AWARE_MULTIPLIERS[key]
    ]
    if seconds < 86400:
        requests.extend(
            (pd.Timedelta(days=days), ICHorizonOrigin("DAY1", days))
            for days in (1, 2, 3, 5)
        )
    return sorted(requests, key=lambda item: item[0])


def _merge_requests(requests) -> tuple[ResolvedICHorizon, ...]:
    ordered: list[pd.Timedelta] = []
    origins: dict[pd.Timedelta, list[ICHorizonOrigin]] = {}
    for duration, origin in requests:
        if duration not in origins:
            origins[duration] = []
            ordered.append(duration)
        if origin not in origins[duration]:
            origins[duration].append(origin)
    return tuple(
        ResolvedICHorizon(DataFreq(duration).name, tuple(origins[duration]))
        for duration in ordered
    )


__all__ = ["ICHorizonOrigin", "ResolvedICHorizon", "resolve_horizon_entries"]
