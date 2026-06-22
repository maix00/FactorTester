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
from .rebalance import BuyAndHold, MembershipChange, OnFactorSignal, RebalanceTrigger


class GroupTargetCalculator:
    """Stateful membership-to-target policy instantiated by one framework run."""

    def __init__(
        self,
        instruments: Sequence[str],
        config: Mapping[str, Any],
    ) -> None:
        self.instruments = tuple(str(value) for value in instruments)
        self.config = dict(config)
        self.strategy_id = str(config.get("strategy_id") or "")
        if not self.strategy_id:
            raise ValueError("strategy_id must not be empty")
        self.strategy_kind = str(config.get("strategy_kind") or "group")
        self.membership_index = int(config.get("membership_index", 0))
        self.long_indices = tuple(int(value) for value in config.get("long_indices", ()))
        self.short_indices = tuple(int(value) for value in config.get("short_indices", ()))
        if self.strategy_kind == "long_short" and (
            not self.long_indices
            or not self.short_indices
            or set(self.long_indices) & set(self.short_indices)
        ):
            raise ValueError("Long-Short requires disjoint non-empty long and short groups")
        self.allocation_name = str(config.get("allocation_policy") or "inverse_volatility")
        self.allocator = _allocator(self.allocation_name)
        self.rebalance_trigger = _rebalance_trigger(
            str(config.get("rebalance_mode") or "on_factor_signal")
        )
        lookback = int(config.get("volatility_lookback") or 20)
        self.estimator = TrailingVolatilityEstimator(
            self.instruments,
            lookback=lookback,
            min_observations=min(
                lookback,
                max(2, int(config.get("volatility_min_observations") or 2)),
            ),
            annualization=float(config.get("volatility_annualization") or 252.0),
        )
        self._previous_prices: np.ndarray | None = None
        self.target_trace: dict[str, dict[str, float]] = {}
        self.fallback_events: list[dict[str, Any]] = []
        self.empty_leg_events: list[dict[str, Any]] = []
        self.overlap_events: list[dict[str, Any]] = []

    def update(
        self,
        timestamp: pd.Timestamp,
        prices: np.ndarray,
        memberships: np.ndarray,
        signal_updates: np.ndarray,
        margin_ratios: np.ndarray,
    ) -> dict[str, float] | None:
        current_prices = np.asarray(prices, dtype=float)
        members = np.asarray(memberships, dtype=bool)
        updates = np.asarray(signal_updates, dtype=bool)
        if current_prices.shape != (len(self.instruments),):
            raise ValueError("price row must match the instrument axis")
        if members.ndim != 2 or members.shape[1] != len(self.instruments):
            raise ValueError("membership row must have source-group and instrument axes")
        if updates.shape != (members.shape[0],):
            raise ValueError("signal-update row must match the source-group axis")
        if self._previous_prices is not None:
            with np.errstate(all="ignore"):
                returns = current_prices / self._previous_prices - 1.0
            self.estimator.update(dict(zip(self.instruments, returns, strict=True)))
        self._previous_prices = current_prices.copy()

        if self.strategy_kind == "long_short":
            active = self.long_indices + self.short_indices
            self._validate_indices(active, members.shape[0])
            if not np.any(updates[list(active)]):
                return None
            long_selected = np.any(members[list(self.long_indices)], axis=0)
            short_selected = np.any(members[list(self.short_indices)], axis=0)
            overlap = long_selected & short_selected
            if np.any(overlap):
                self.overlap_events.append({
                    "timestamp": pd.Timestamp(timestamp).isoformat(),
                    "overlap_count": int(np.count_nonzero(overlap)),
                    "instruments": [
                        instrument for instrument, is_overlap in zip(
                            self.instruments, overlap, strict=True
                        )
                        if bool(is_overlap)
                    ],
                })
                long_selected = long_selected & ~overlap
                short_selected = short_selected & ~overlap
            selected = long_selected | short_selected
            if not self.rebalance_trigger.should_rebalance(timestamp, selected):
                return None
            if not np.any(long_selected) or not np.any(short_selected):
                self.empty_leg_events.append({
                    "timestamp": pd.Timestamp(timestamp).isoformat(),
                    "long_count": int(np.count_nonzero(long_selected)),
                    "short_count": int(np.count_nonzero(short_selected)),
                })
                return None
            weights = self._allocate(timestamp, long_selected, margin_ratios, 0.5, "long")
            weights -= self._allocate(timestamp, short_selected, margin_ratios, 0.5, "short")
        else:
            self._validate_indices((self.membership_index,), members.shape[0])
            if not updates[self.membership_index]:
                return None
            selected = (
                members[self.membership_index]
                & np.isfinite(current_prices)
                & (current_prices > 0)
            )
            if not self.rebalance_trigger.should_rebalance(timestamp, selected):
                return None
            weights = self._allocate(timestamp, selected, margin_ratios, 1.0, None)

        target = {
            instrument: float(weight)
            for instrument, weight in zip(self.instruments, weights, strict=True)
            if not np.isclose(weight, 0.0)
        }
        self.target_trace[pd.Timestamp(timestamp).isoformat()] = target
        return target

    def _allocate(
        self,
        timestamp: pd.Timestamp,
        selected: np.ndarray,
        margin_ratios: np.ndarray,
        gross_exposure: float,
        leg: str | None,
    ) -> np.ndarray:
        volatilities = self.estimator.snapshot()
        inputs = AllocationInput(
            self.instruments,
            selected,
            gross_exposure=gross_exposure,
            volatilities=volatilities,
            margin_ratios=dict(zip(self.instruments, margin_ratios, strict=True)),
        )
        try:
            return self.allocator.allocate(inputs)
        except AllocationInputsUnavailable as exc:
            if self.allocation_name != "inverse_volatility" or str(
                self.config.get("volatility_warmup") or "equal_notional"
            ) != "equal_notional":
                raise
            self.fallback_events.append({
                "timestamp": pd.Timestamp(timestamp).isoformat(),
                "leg": leg,
                "reason": str(exc),
                "fallback_policy": "equal_notional",
                "volatilities": volatilities,
            })
            return EqualNotionalAllocator().allocate(inputs)

    @staticmethod
    def _validate_indices(indices: tuple[int, ...], group_count: int) -> None:
        if not indices or min(indices) < 0 or max(indices) >= group_count:
            raise ValueError("strategy membership index is outside the source-group axis")

    @property
    def diagnostics(self) -> dict[str, Any]:
        return {
            "volatility_warmup_fallback_count": len(self.fallback_events),
            "volatility_warmup_fallbacks": self.fallback_events,
            "long_short_empty_leg_count": len(self.empty_leg_events),
            "long_short_empty_legs": self.empty_leg_events,
            "long_short_overlap_count": len(self.overlap_events),
            "long_short_overlaps": self.overlap_events,
            "last_volatilities": self.estimator.snapshot(),
        }


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
    """Research helper; execution adapters calculate targets in their own lifecycle."""

    index = pd.DatetimeIndex(timestamps)
    names = tuple(str(value) for value in instruments)
    members = np.asarray(membership, dtype=bool)
    price_values = np.asarray(prices, dtype=float)
    if members.ndim != 3 or members.shape[0] != len(index) or members.shape[2] != len(names):
        raise ValueError(
            "membership must have timestamp, source-group, and instrument axes"
        )
    if price_values.shape != (len(index), len(names)):
        raise ValueError("price matrix does not match timestamp and instrument axes")
    update_values = (
        np.ones(members.shape[:2], dtype=bool)
        if signal_updates is None else np.asarray(signal_updates, dtype=bool)
    )
    if update_values.shape != members.shape[:2]:
        raise ValueError("signal-update mask must match membership time/source-group axes")
    if not index.is_unique or not index.is_monotonic_increasing:
        raise ValueError("target timestamps must be unique and increasing")
    if initial_cash <= 0:
        raise ValueError("initial cash must be positive")

    margin_values = _rule_matrix(margin_ratios, price_values.shape, 1.0, "margin ratios")
    multiplier_values = _rule_matrix(multipliers, price_values.shape, 1.0, "multipliers")
    lot_values = _rule_matrix(lot_sizes, price_values.shape, 1.0, "lot sizes")
    strategies = []
    for position, config in enumerate(strategy_configs):
        if str(config.get("strategy_kind") or "group") == "long_short":
            strategies.append(_compile_long_short_strategy(
                index, names, members, price_values, margin_values, config, update_values
            ))
            continue
        membership_index = int(config.get("membership_index", position))
        if membership_index < 0 or membership_index >= members.shape[1]:
            raise ValueError(
                f"strategy {config.get('strategy_id')!r} references membership index "
                f"{membership_index}, available=0..{members.shape[1] - 1}"
            )
        strategies.append(_compile_strategy(
            index,
            names,
            members[:, membership_index, :],
            price_values,
            margin_values,
            config,
            update_values[:, membership_index],
        ))
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
    rebalance_trigger = _rebalance_trigger(rebalance_name)
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
        if not rebalance_trigger.should_rebalance(timestamp, selected):
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


def _compile_long_short_strategy(
    index: pd.DatetimeIndex,
    instruments: tuple[str, ...],
    memberships: np.ndarray,
    prices: np.ndarray,
    margin_ratios: np.ndarray,
    config: Mapping[str, Any],
    signal_updates: np.ndarray,
) -> dict[str, Any]:
    long_indices = tuple(int(value) for value in config.get("long_indices", ()))
    short_indices = tuple(int(value) for value in config.get("short_indices", ()))
    if not long_indices or not short_indices or set(long_indices) & set(short_indices):
        raise ValueError("Long-Short requires disjoint non-empty long and short groups")
    if min(long_indices + short_indices) < 0 or max(long_indices + short_indices) >= memberships.shape[1]:
        raise ValueError("Long-Short membership index is outside the source-group axis")
    allocation_name = str(config.get("allocation_policy") or "inverse_volatility")
    allocator = _allocator(allocation_name)
    rebalance_trigger = _rebalance_trigger(str(config.get("rebalance_mode") or "on_factor_signal"))
    lookback = int(config.get("volatility_lookback") or 20)
    estimator = TrailingVolatilityEstimator(
        instruments,
        lookback=lookback,
        min_observations=min(lookback, max(2, int(config.get("volatility_min_observations") or 2))),
        annualization=float(config.get("volatility_annualization") or 252.0),
    )
    targets = {}
    fallback_events = []
    empty_leg_events = []
    overlap_events = []
    previous_prices = None
    active_indices = long_indices + short_indices
    for row, timestamp in enumerate(index):
        current_prices = prices[row]
        if previous_prices is not None:
            with np.errstate(all="ignore"):
                returns = current_prices / previous_prices - 1.0
            estimator.update(dict(zip(instruments, returns, strict=True)))
        previous_prices = current_prices.copy()
        if not np.any(signal_updates[row, active_indices]):
            continue
        long_selected = np.any(memberships[row, long_indices, :], axis=0)
        short_selected = np.any(memberships[row, short_indices, :], axis=0)
        overlap = long_selected & short_selected
        if np.any(overlap):
            overlap_events.append({
                "timestamp": timestamp.isoformat(),
                "overlap_count": int(np.count_nonzero(overlap)),
                "instruments": [
                    instrument for instrument, is_overlap in zip(
                        instruments, overlap, strict=True
                    )
                    if bool(is_overlap)
                ],
            })
            long_selected = long_selected & ~overlap
            short_selected = short_selected & ~overlap
        active = long_selected | short_selected
        if not rebalance_trigger.should_rebalance(timestamp, active):
            continue
        if not np.any(long_selected) or not np.any(short_selected):
            empty_leg_events.append({
                "timestamp": timestamp.isoformat(),
                "long_count": int(np.count_nonzero(long_selected)),
                "short_count": int(np.count_nonzero(short_selected)),
            })
            continue
        volatilities = estimator.snapshot()
        margin = dict(zip(instruments, margin_ratios[row], strict=True))
        leg_weights = []
        for side, selected in ((1.0, long_selected), (-1.0, short_selected)):
            inputs = AllocationInput(
                instruments,
                selected,
                gross_exposure=0.5,
                volatilities=volatilities,
                margin_ratios=margin,
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
                    "leg": "long" if side > 0 else "short",
                    "reason": str(exc),
                    "fallback_policy": "equal_notional",
                    "volatilities": volatilities,
                })
            leg_weights.append(side * weights)
        combined = leg_weights[0] + leg_weights[1]
        targets[timestamp.isoformat()] = {
            instrument: float(weight)
            for instrument, weight in zip(instruments, combined, strict=True)
            if not np.isclose(weight, 0.0)
        }
    strategy_id = str(config.get("strategy_id") or "")
    return {
        "strategy_id": strategy_id,
        "strategy_kind": "long_short",
        "rebalance_mode": str(config.get("rebalance_mode") or "on_factor_signal"),
        "allocation_policy": allocation_name,
        "fee_rate": float(config.get("fee_rate") or 0.0),
        "initial_capital": float(config.get("initial_capital") or 0.0) or None,
        "targets": targets,
        "diagnostics": {
            "volatility_warmup_fallback_count": len(fallback_events),
            "volatility_warmup_fallbacks": fallback_events,
            "long_short_empty_leg_count": len(empty_leg_events),
            "long_short_empty_legs": empty_leg_events,
            "long_short_overlap_count": len(overlap_events),
            "long_short_overlaps": overlap_events,
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


def _rebalance_trigger(name: str) -> RebalanceTrigger:
    if name == "on_factor_signal":
        return OnFactorSignal()
    if name == "membership_change":
        return MembershipChange()
    if name == "buy_and_hold":
        return BuyAndHold()
    raise ValueError(f"unsupported rebalance trigger: {name}")


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
