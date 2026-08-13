"""Requested and resolved forward-return horizons for IC tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

from tools.data.types import DataFreq

from .horizon_resolution import ResolvedICHorizon, resolve_horizon_entries


def _texts(values: Iterable[Any], *, field: str) -> tuple[str, ...]:
    result = tuple(dict.fromkeys(str(item or "").strip() for item in values))
    if not result or any(not item for item in result):
        raise ValueError(f"{field} requires non-empty values")
    return result


def _positive_integers(values: Iterable[Any]) -> tuple[int, ...]:
    result: list[int] = []
    for value in values:
        if isinstance(value, bool):
            raise ValueError("horizon multipliers must be positive integers")
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("horizon multipliers must be positive integers") from exc
        if number < 1 or number != value:
            raise ValueError("horizon multipliers must be positive integers")
        if number not in result:
            result.append(number)
    if not result:
        raise ValueError("horizon multipliers require at least one value")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ICHorizonPolicy:
    """A compact base × multiplier request resolved per factor frequency."""

    mode: str
    bases: tuple[str, ...] = ()
    multipliers: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in {"scale_aware", "explicit"}:
            raise ValueError("horizon mode must be scale_aware or explicit")
        if self.mode == "scale_aware":
            object.__setattr__(self, "bases", ())
            object.__setattr__(self, "multipliers", ())
            return
        bases = _texts(self.bases or ("signal",), field="horizon bases")
        for base in bases:
            if base == "signal":
                continue
            try:
                if DataFreq(base).value <= pd.Timedelta(0):
                    raise ValueError
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid horizon base: {base}") from exc
        object.__setattr__(self, "bases", bases)
        object.__setattr__(
            self,
            "multipliers",
            _positive_integers(self.multipliers or (1,)),
        )

    @classmethod
    def from_value(cls, value: Any) -> ICHorizonPolicy:
        if value is None:
            return cls("scale_aware")
        if not isinstance(value, dict):
            raise ValueError("forward_return_horizons must be an object")
        sampling = str(value.get("sampling") or "explicit").strip().lower()
        if sampling in {"scale_aware", "auto"}:
            return cls("scale_aware")
        if sampling not in {"explicit", ""}:
            raise ValueError("horizon sampling must be explicit or scale_aware")
        return cls(
            "explicit",
            tuple(value.get("bases") or ("signal",)),
            tuple(value.get("multipliers") or (1,)),
        )

    @classmethod
    def from_dict(cls, value: Any) -> ICHorizonPolicy:
        if not isinstance(value, dict):
            raise ValueError("horizon policy must be an object")
        mode = str(value.get("mode") or "").strip()
        return cls(
            mode,
            tuple(value.get("bases") or ()),
            tuple(value.get("multipliers") or ()),
        )

    def resolve(self, signal_frequency: Any | None) -> tuple[str, ...]:
        return tuple(
            item.physical_frequency
            for item in self.resolve_entries(signal_frequency)
        )

    def resolve_entries(
        self, signal_frequency: Any | None,
    ) -> tuple[ResolvedICHorizon, ...]:
        return resolve_horizon_entries(
            self.mode, self.bases, self.multipliers, signal_frequency,
        )

    def to_dict(self) -> dict[str, Any]:
        if self.mode == "scale_aware":
            return {"mode": "scale_aware"}
        return {
            "mode": "explicit",
            "bases": list(self.bases),
            "multipliers": list(self.multipliers),
        }
__all__ = ["ICHorizonPolicy"]
