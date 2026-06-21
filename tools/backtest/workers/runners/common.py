"""Validation helpers shared by isolated target-weight workers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ...strategies.targets import compile_group_target_payload


@dataclass(frozen=True, slots=True)
class TargetWeightInput:
    timestamps: tuple[pd.Timestamp, ...]
    instruments: tuple[str, ...]
    prices: dict[str, tuple[float, ...]]
    strategies: tuple[Mapping[str, Any], ...]
    initial_cash: float
    multipliers: tuple[tuple[float, ...], ...]
    lot_sizes: tuple[tuple[float, ...], ...]
    margin_ratios: tuple[tuple[float, ...], ...]


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
    rules = payload.get("market_rules", {})
    multipliers = _parse_rule_matrix(
        rules.get("multipliers"), len(timestamps), len(instruments), "multipliers"
    )
    lot_sizes = _parse_rule_matrix(
        rules.get("lot_sizes"), len(timestamps), len(instruments), "lot_sizes"
    )
    margin_ratios = _parse_rule_matrix(
        rules.get("margin_ratios"), len(timestamps), len(instruments), "margin ratios"
    )
    return TargetWeightInput(
        timestamps,
        instruments,
        prices,
        strategies,
        initial_cash,
        multipliers,
        lot_sizes,
        margin_ratios,
    )


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
        if sum(abs(value) for value in normalized_weights.values()) > 2.0 + 1e-9:
            raise ValueError("target gross exposure cannot exceed two")
        result[normalized_timestamp] = normalized_weights
    return result


def rebalance_mode(strategy: Mapping[str, Any]) -> str:
    mode = str(strategy.get("rebalance_mode", "on_factor_signal"))
    if mode not in {"on_factor_signal", "membership_change", "buy_and_hold", "scheduled"}:
        raise ValueError(f"unsupported rebalance mode: {mode}")
    return mode


def target_quantities(
    request: TargetWeightInput,
    row: int,
    weights: Mapping[str, float],
    portfolio_value: float,
) -> dict[str, float]:
    result = {}
    for position, instrument in enumerate(request.instruments):
        price = request.prices[instrument][row]
        multiplier = request.multipliers[row][position]
        lot_size = request.lot_sizes[row][position]
        raw = abs(float(weights.get(instrument, 0.0))) * portfolio_value / (
            price * multiplier
        )
        lots = int(raw / lot_size + 1e-12)
        result[instrument] = np.sign(float(weights.get(instrument, 0.0))) * lots * lot_size
    return result


def valuation_price(request: TargetWeightInput, row: int, instrument: str) -> float:
    position = request.instruments.index(instrument)
    return request.prices[instrument][row] * request.multipliers[row][position]


def _parse_rule_matrix(
    value: Any,
    rows: int,
    columns: int,
    label: str,
) -> tuple[tuple[float, ...], ...]:
    if value is None:
        return tuple(tuple(1.0 for _ in range(columns)) for _ in range(rows))
    if not isinstance(value, list) or len(value) != rows:
        raise ValueError(f"{label} must contain one row per timestamp")
    result = tuple(tuple(float(item) for item in row) for row in value)
    if any(len(row) != columns for row in result) or any(
        not np.isfinite(item) or item <= 0 for row in result for item in row
    ):
        raise ValueError(f"{label} must be a positive finite timestamp/instrument matrix")
    return result


def compile_group_strategy_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Calculate targets inside one framework worker from canonical raw inputs."""

    timestamps = tuple(pd.Timestamp(value) for value in payload.get("timestamps", ()))
    instruments = tuple(str(value) for value in payload.get("instruments", ()))
    raw_prices = payload.get("prices", {})
    if not timestamps or not instruments or not isinstance(raw_prices, Mapping):
        raise ValueError("group strategy input requires timestamps, instruments, and prices")
    prices = np.asarray([
        [float(raw_prices[instrument][row]) for instrument in instruments]
        for row in range(len(timestamps))
    ])
    rules = payload.get("market_rules", {})
    return compile_group_target_payload(
        timestamps=timestamps,
        instruments=instruments,
        membership=np.asarray(payload.get("membership"), dtype=bool),
        prices=prices,
        strategy_configs=tuple(payload.get("strategy_configs", ())),
        initial_cash=float(payload.get("initial_cash", 0.0)),
        margin_ratios=np.asarray(rules.get("margin_ratios"), dtype=float)
        if rules.get("margin_ratios") is not None else None,
        multipliers=np.asarray(rules.get("multipliers"), dtype=float)
        if rules.get("multipliers") is not None else None,
        lot_sizes=np.asarray(rules.get("lot_sizes"), dtype=float)
        if rules.get("lot_sizes") is not None else None,
        signal_updates=np.asarray(payload.get("signal_updates"), dtype=bool)
        if payload.get("signal_updates") is not None else None,
    )
