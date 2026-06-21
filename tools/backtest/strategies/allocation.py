"""Portfolio allocation policies, independent of sizing and margin constraints."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True, slots=True)
class AllocationInput:
    instruments: tuple[str, ...]
    selected: np.ndarray
    gross_exposure: float = 1.0
    volatilities: Mapping[str, float] | None = None
    margin_ratios: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        selected = np.asarray(self.selected, dtype=bool)
        if selected.shape != (len(self.instruments),):
            raise ValueError("selected mask must match the instrument axis")
        if not 0 < self.gross_exposure <= 1:
            raise ValueError("gross exposure must be within (0, 1]")
        object.__setattr__(self, "selected", selected)


class WeightAllocator(Protocol):
    name: str

    def allocate(self, inputs: AllocationInput) -> np.ndarray: ...


class AllocationInputsUnavailable(ValueError):
    """A policy cannot run yet because required causal inputs are unavailable."""


@dataclass(frozen=True, slots=True)
class EqualNotionalAllocator:
    name: str = "equal_notional"

    def allocate(self, inputs: AllocationInput) -> np.ndarray:
        return _normalize_selected(inputs, np.ones(len(inputs.instruments)))


@dataclass(frozen=True, slots=True)
class InverseVolatilityAllocator:
    """Inverse-volatility equal-risk approximation using trailing-only estimates."""

    volatility_floor: float = 1e-8
    name: str = "inverse_volatility"

    def allocate(self, inputs: AllocationInput) -> np.ndarray:
        if inputs.volatilities is None:
            raise AllocationInputsUnavailable(
                "inverse_volatility requires trailing volatility estimates"
            )
        raw = np.zeros(len(inputs.instruments), dtype=float)
        missing = []
        for index, instrument in enumerate(inputs.instruments):
            if not inputs.selected[index]:
                continue
            volatility = float(inputs.volatilities.get(instrument, np.nan))
            if np.isfinite(volatility) and volatility >= 0:
                raw[index] = 1.0 / max(volatility, self.volatility_floor)
            else:
                missing.append(f"{instrument}={volatility!r}")
        if missing:
            raise AllocationInputsUnavailable(
                "inverse_volatility has no usable trailing volatility for "
                + ", ".join(missing)
            )
        return _normalize_selected(inputs, raw)


@dataclass(frozen=True, slots=True)
class EqualMarginAllocator:
    """Comparison policy: equal initial-margin budget, not equal risk."""

    name: str = "equal_margin"

    def allocate(self, inputs: AllocationInput) -> np.ndarray:
        if inputs.margin_ratios is None:
            raise AllocationInputsUnavailable("equal_margin requires margin ratios")
        raw = np.zeros(len(inputs.instruments), dtype=float)
        for index, instrument in enumerate(inputs.instruments):
            if not inputs.selected[index]:
                continue
            ratio = float(inputs.margin_ratios.get(instrument, np.nan))
            if np.isfinite(ratio) and ratio > 0:
                raw[index] = 1.0 / ratio
        return _normalize_selected(inputs, raw)


class TrailingVolatilityEstimator:
    """Causal per-instrument sample volatility with explicit warm-up."""

    def __init__(
        self,
        instruments: tuple[str, ...],
        *,
        lookback: int = 20,
        min_observations: int | None = None,
        annualization: float = 252.0,
    ) -> None:
        if lookback < 2 or annualization <= 0:
            raise ValueError("invalid volatility estimator configuration")
        minimum = lookback if min_observations is None else min_observations
        if minimum < 2 or minimum > lookback:
            raise ValueError("min observations must be within [2, lookback]")
        self.instruments = instruments
        self.lookback = lookback
        self.min_observations = minimum
        self.annualization = annualization
        self._returns = {name: deque(maxlen=lookback) for name in instruments}

    def update(self, returns: Mapping[str, float]) -> None:
        for instrument in self.instruments:
            value = float(returns.get(instrument, np.nan))
            if np.isfinite(value):
                self._returns[instrument].append(value)

    def snapshot(self) -> dict[str, float]:
        result = {}
        scale = self.annualization ** 0.5
        for instrument, values in self._returns.items():
            result[instrument] = (
                float(np.std(values, ddof=1) * scale)
                if len(values) >= self.min_observations else np.nan
            )
        return result


def _normalize_selected(inputs: AllocationInput, raw: np.ndarray) -> np.ndarray:
    raw = np.where(inputs.selected & np.isfinite(raw) & (raw > 0), raw, 0.0)
    total = float(raw.sum())
    if total <= 0:
        raise ValueError("selected instruments have no usable allocation inputs")
    return raw / total * inputs.gross_exposure
