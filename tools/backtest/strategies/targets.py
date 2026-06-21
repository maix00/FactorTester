"""Compile group memberships into framework-neutral target-weight signals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from .allocation import (
    AllocationInputsUnavailable,
    AllocationInput,
    EqualMarginAllocator,
    EqualNotionalAllocator,
    InverseVolatilityAllocator,
    TrailingVolatilityEstimator,
)
from .rebalance import BuyAndHold, MembershipChange, OnFactorSignal, RebalancePolicy


def compile_group_target_payload(
    *,
    timestamps: Sequence[Any],
    instruments: Sequence[str],
    membership: np.ndarray,
    prices: np.ndarray,
    strategy_configs: Sequence[Mapping[str, Any]],
    initial_cash: float,
    margin_ratios: np.ndarray | None = None,
    multipliers: np.ndarray | None = None,
    lot_sizes: np.ndarray | None = None,
    signal_updates: np.ndarray | None = None,
) -> dict[str, Any]:
    """Create one causal target stream consumed unchanged by every engine."""

    index = pd.DatetimeIndex(timestamps)
    names = tuple(str(value) for value in instruments)
    members = np.asarray(membership, dtype=bool)
    price_values = np.asarray(prices, dtype=float)
    expected = (len(index), len(strategy_configs), len(names))
    if members.shape != expected:
        raise ValueError(f"membership shape {members.shape} does not match {expected}")
    if price_values.shape != (len(index), len(names)):
        raise ValueError("price matrix does not match timestamp and instrument axes")
    update_values = (
        np.ones((len(index), len(strategy_configs)), dtype=bool)
        if signal_updates is None else np.asarray(signal_updates, dtype=bool)
    )
    if update_values.shape != (len(index), len(strategy_configs)):
        raise ValueError("signal-update mask must match timestamp and strategy axes")
    if not index.is_unique or not index.is_monotonic_increasing:
        raise ValueError("target timestamps must be unique and increasing")
    if initial_cash <= 0:
        raise ValueError("initial cash must be positive")

    margin_values = _rule_matrix(margin_ratios, price_values.shape, 1.0, "margin ratios")
    multiplier_values = _rule_matrix(multipliers, price_values.shape, 1.0, "multipliers")
    lot_values = _rule_matrix(lot_sizes, price_values.shape, 1.0, "lot sizes")
    strategies = [
        _compile_strategy(
            index,
            names,
            members[:, position, :],
            price_values,
            margin_values,
            config,
            update_values[:, position],
        )
        for position, config in enumerate(strategy_configs)
    ]
    return {
        "timestamps": [timestamp.isoformat() for timestamp in index],
        "instruments": list(names),
        "prices": {
            instrument: price_values[:, position].tolist()
            for position, instrument in enumerate(names)
        },
        "market_rules": {
            "multipliers": multiplier_values.tolist(),
            "lot_sizes": lot_values.tolist(),
            "margin_ratios": margin_values.tolist(),
        },
        "initial_cash": float(initial_cash),
        "strategies": strategies,
    }


def _compile_strategy(
    index: pd.DatetimeIndex,
    instruments: tuple[str, ...],
    membership: np.ndarray,
    prices: np.ndarray,
    margin_ratios: np.ndarray,
    config: Mapping[str, Any],
    signal_updates: np.ndarray,
) -> dict[str, Any]:
    strategy_id = str(config.get("strategy_id") or "")
    if not strategy_id:
        raise ValueError("strategy_id must not be empty")
    allocation_name = str(config.get("allocation_policy") or "inverse_volatility")
    rebalance_name = str(config.get("rebalance_mode") or "on_factor_signal")
    allocator = _allocator(allocation_name)
    rebalance = _rebalance_policy(rebalance_name)
    lookback = int(config.get("volatility_lookback") or 20)
    estimator = TrailingVolatilityEstimator(
        instruments,
        lookback=lookback,
        min_observations=min(lookback, max(2, int(config.get("volatility_min_observations") or 2))),
        annualization=float(config.get("volatility_annualization") or 252.0),
    )
    targets: dict[str, dict[str, float]] = {}
    fallback_events: list[dict[str, Any]] = []
    previous_prices: np.ndarray | None = None
    for row, timestamp in enumerate(index):
        current_prices = prices[row]
        if previous_prices is not None:
            with np.errstate(all="ignore"):
                returns = current_prices / previous_prices - 1.0
            estimator.update(dict(zip(instruments, returns, strict=True)))
        previous_prices = current_prices.copy()
        if not signal_updates[row]:
            continue
        selected = membership[row] & np.isfinite(current_prices) & (current_prices > 0)
        if not rebalance.should_rebalance(timestamp, selected):
            continue
        volatilities = estimator.snapshot()
        inputs = AllocationInput(
            instruments,
            selected,
            volatilities=volatilities,
            margin_ratios=dict(zip(instruments, margin_ratios[row], strict=True)),
        )
        try:
            weights = allocator.allocate(inputs)
        except AllocationInputsUnavailable as exc:
            if allocation_name != "inverse_volatility" or str(
                config.get("volatility_warmup") or "equal_notional"
            ) != "equal_notional":
                raise
            weights = EqualNotionalAllocator().allocate(inputs)
            fallback_events.append({
                "timestamp": timestamp.isoformat(),
                "reason": str(exc),
                "fallback_policy": "equal_notional",
                "volatilities": volatilities,
            })
        targets[timestamp.isoformat()] = {
            instrument: float(weight)
            for instrument, weight in zip(instruments, weights, strict=True)
            if not np.isclose(weight, 0.0)
        }
    return {
        "strategy_id": strategy_id,
        "rebalance_mode": rebalance_name,
        "allocation_policy": allocation_name,
        "fee_rate": float(config.get("fee_rate") or 0.0),
        "initial_capital": float(config.get("initial_capital") or 0.0) or None,
        "targets": targets,
        "diagnostics": {
            "volatility_warmup_fallback_count": len(fallback_events),
            "volatility_warmup_fallbacks": fallback_events,
            "last_volatilities": estimator.snapshot(),
        },
    }


def _allocator(name: str):
    if name == "inverse_volatility":
        return InverseVolatilityAllocator()
    if name == "equal_notional":
        return EqualNotionalAllocator()
    if name == "equal_margin":
        return EqualMarginAllocator()
    raise ValueError(f"unsupported allocation policy: {name}")


def _rebalance_policy(name: str) -> RebalancePolicy:
    if name == "on_factor_signal":
        return OnFactorSignal()
    if name == "membership_change":
        return MembershipChange()
    if name == "buy_and_hold":
        return BuyAndHold()
    raise ValueError(f"unsupported rebalance policy: {name}")


def _rule_matrix(
    value: np.ndarray | None,
    shape: tuple[int, int],
    default: float,
    label: str,
) -> np.ndarray:
    result = np.full(shape, default, dtype=float) if value is None else np.asarray(value, dtype=float)
    if result.shape != shape or np.any(~np.isfinite(result)) or np.any(result <= 0):
        raise ValueError(f"{label} must be a positive finite matrix with shape {shape}")
    return result
