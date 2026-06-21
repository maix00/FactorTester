"""Validation helpers shared by isolated target-weight workers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True, slots=True)
class TargetWeightInput:
    timestamps: tuple[pd.Timestamp, ...]
    instruments: tuple[str, ...]
    prices: dict[str, tuple[float, ...]]
    strategies: tuple[Mapping[str, Any], ...]
    initial_cash: float


def parse_target_weight_input(payload: Mapping[str, Any]) -> TargetWeightInput:
    timestamps = tuple(pd.Timestamp(value) for value in payload.get("timestamps", ()))
    instruments = tuple(str(value) for value in payload.get("instruments", ()))
    strategies = tuple(payload.get("strategies", ()))
    initial_cash = float(payload.get("initial_cash", 0.0))
    if not timestamps or not instruments or not strategies or initial_cash <= 0:
        raise ValueError(
            "target-weight run requires timestamps, instruments, strategies, and positive cash"
        )
    if len(set(timestamps)) != len(timestamps) or tuple(sorted(timestamps)) != timestamps:
        raise ValueError("timestamps must be unique and increasing")
    if len(set(instruments)) != len(instruments):
        raise ValueError("instruments must be unique")

    raw_prices = payload.get("prices", {})
    prices: dict[str, tuple[float, ...]] = {}
    for instrument in instruments:
        values = raw_prices.get(instrument)
        if not isinstance(values, list) or len(values) != len(timestamps):
            raise ValueError(f"price length mismatch for {instrument}")
        normalized = tuple(float(value) for value in values)
        if any(value <= 0 for value in normalized):
            raise ValueError(f"prices must be positive for {instrument}")
        prices[instrument] = normalized

    strategy_ids = [str(strategy.get("strategy_id", "")) for strategy in strategies]
    if any(not value for value in strategy_ids) or len(set(strategy_ids)) != len(strategy_ids):
        raise ValueError("strategy ids must be non-empty and unique")
    return TargetWeightInput(timestamps, instruments, prices, strategies, initial_cash)


def target_rows(
    strategy: Mapping[str, Any], timestamps: tuple[pd.Timestamp, ...]
) -> dict[pd.Timestamp, dict[str, float]]:
    allowed = set(timestamps)
    result = {}
    for timestamp, weights in strategy.get("targets", {}).items():
        normalized_timestamp = pd.Timestamp(timestamp)
        if normalized_timestamp not in allowed:
            raise ValueError(f"target timestamp is outside the price index: {timestamp}")
        if not isinstance(weights, Mapping):
            raise ValueError("target weights must be an object")
        normalized_weights = {str(key): float(value) for key, value in weights.items()}
        if any(value < 0 for value in normalized_weights.values()):
            raise ValueError("cash target-weight workers do not support short weights")
        if sum(normalized_weights.values()) > 1.0 + 1e-9:
            raise ValueError("target weights cannot exceed one")
        result[normalized_timestamp] = normalized_weights
    return result


def rebalance_mode(strategy: Mapping[str, Any]) -> str:
    mode = str(strategy.get("rebalance_mode", "membership_change"))
    if mode not in {"membership_change", "each_period", "buy_and_hold"}:
        raise ValueError(f"unsupported rebalance mode: {mode}")
    return mode
