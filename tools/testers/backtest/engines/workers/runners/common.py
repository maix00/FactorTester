"""Validation helpers shared by isolated target-weight workers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ...strategies.targets import GroupTargetCalculator
from tools.testers.settings.strategy_fields import validate_resolved_strategy_settings


def should_report_progress(completed: int, total: int, max_updates: int = 100) -> bool:
    """Bound progress transport cost without changing event replay semantics."""
    if total <= 0 or completed <= 1 or completed >= total:
        return True
    stride = max(1, int(np.ceil(total / max(max_updates, 1))))
    return completed % stride == 0


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
    volumes: dict[str, tuple[float, ...]] | None = None


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
    for strategy in strategies:
        validate_resolved_strategy_settings(strategy)
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
    raw_volumes = payload.get("volumes")
    volumes = None
    if raw_volumes is not None:
        volumes = {}
        for instrument in instruments:
            values = raw_volumes.get(instrument) if isinstance(raw_volumes, Mapping) else None
            if not isinstance(values, list) or len(values) != len(timestamps):
                raise ValueError(f"volume length mismatch for {instrument}")
            normalized = tuple(float(value) for value in values)
            if any(not np.isfinite(value) or value < 0 for value in normalized):
                raise ValueError(f"volumes must be finite and non-negative for {instrument}")
            volumes[instrument] = normalized
    if volumes is None and any(
        str(strategy.get("liquidity_mode") or "infinite") == "volume_participation"
        for strategy in strategies
    ):
        raise ValueError("volume_participation requires observed volume data")
    return TargetWeightInput(
        timestamps,
        instruments,
        prices,
        strategies,
        initial_cash,
        multipliers,
        lot_sizes,
        margin_ratios,
        volumes,
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


def target_quantities(
    request: TargetWeightInput,
    row: int,
    weights: Mapping[str, float],
    portfolio_value: float,
    strategy: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    weights = approved_weights(request, row, weights, strategy or {})
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


def approved_weights(
    request: TargetWeightInput,
    row: int,
    weights: Mapping[str, float],
    strategy: Mapping[str, Any],
) -> dict[str, float]:
    normalized = {str(key): float(value) for key, value in weights.items()}
    if str(strategy.get("margin_mode") or "none") == "none":
        return normalized
    collateral = float(strategy.get("collateral_fraction") or 1.0)
    required = sum(
        abs(normalized.get(instrument, 0.0)) * request.margin_ratios[row][position]
        for position, instrument in enumerate(request.instruments)
    )
    if required <= collateral + 1e-12:
        return normalized
    scale = collateral / required
    return {instrument: value * scale for instrument, value in normalized.items()}


def valuation_price(request: TargetWeightInput, row: int, instrument: str) -> float:
    position = request.instruments.index(instrument)
    return request.prices[instrument][row] * request.multipliers[row][position]


def portfolio_value(
    request: TargetWeightInput,
    row: int,
    positions: Mapping[str, float],
    cash: float,
) -> float:
    return float(cash) + sum(
        float(positions.get(instrument, 0.0)) * valuation_price(request, row, instrument)
        for instrument in request.instruments
    )


def executable_deltas(
    request: TargetWeightInput,
    row: int,
    strategy: Mapping[str, Any],
    desired: Mapping[str, float],
    current: Mapping[str, float],
    cash: float,
) -> dict[str, float]:
    deltas = capacity_limited_deltas(request, row, strategy, desired, current)
    fee_rate = float(strategy.get("fee_rate") or 0.0)
    available = float(cash)
    buy_cost = 0.0
    for instrument, delta in deltas.items():
        if abs(delta) <= 1e-12:
            continue
        price = execution_price(valuation_price(request, row, instrument), delta, strategy)
        notional = abs(delta) * price
        if delta < 0:
            available += notional - notional * fee_rate
        else:
            buy_cost += notional * (1.0 + fee_rate)
    if buy_cost <= max(available, 0.0) + 1e-9:
        return deltas
    if buy_cost <= 0.0 or available <= 0.0:
        return {
            instrument: (delta if delta < 0 else 0.0)
            for instrument, delta in deltas.items()
        }
    scale = available / buy_cost
    adjusted = dict(deltas)
    for position, instrument in enumerate(request.instruments):
        delta = adjusted.get(instrument, 0.0)
        if delta <= 0:
            continue
        lot_size = request.lot_sizes[row][position]
        adjusted[instrument] = float(
            int((delta * scale) / lot_size + 1e-12) * lot_size
        )
    return adjusted


def apply_deltas(
    request: TargetWeightInput,
    row: int,
    strategy: Mapping[str, Any],
    positions: Mapping[str, float],
    cash: float,
    deltas: Mapping[str, float],
) -> tuple[float, dict[str, float]]:
    updated = {
        instrument: float(positions.get(instrument, 0.0))
        for instrument in request.instruments
    }
    next_cash = float(cash)
    fee_rate = float(strategy.get("fee_rate") or 0.0)
    for sell_first in (True, False):
        for instrument in request.instruments:
            delta = float(deltas.get(instrument, 0.0))
            if abs(delta) <= 1e-12 or (delta < 0) != sell_first:
                continue
            fill_price = execution_price(
                valuation_price(request, row, instrument), delta, strategy
            )
            trade_value = abs(delta) * fill_price
            fee = trade_value * fee_rate
            next_cash -= delta * fill_price + fee
            updated[instrument] += delta
    return next_cash, updated


def execute_target_weights(
    request: TargetWeightInput,
    row: int,
    strategy: Mapping[str, Any],
    target: Mapping[str, float],
    positions: Mapping[str, float],
    cash: float,
    current_value: float | None = None,
) -> tuple[float, dict[str, float], dict[str, float]]:
    desired = target_quantities(
        request,
        row,
        target,
        float(current_value)
        if current_value is not None
        else portfolio_value(request, row, positions, cash),
        strategy,
    )
    deltas = executable_deltas(request, row, strategy, desired, positions, cash)
    next_cash, next_positions = apply_deltas(
        request, row, strategy, positions, cash, deltas
    )
    return next_cash, next_positions, deltas


def execution_timing(strategy: Mapping[str, Any]) -> str:
    timing = str(strategy.get("execution_timing") or "next_bar")
    if timing not in {"next_bar", "same_bar"}:
        raise ValueError(f"unsupported execution_timing: {timing}")
    return timing


def execution_delay_bars(strategy: Mapping[str, Any]) -> int:
    timing = execution_timing(strategy)
    if timing == "same_bar":
        return 0
    delay = int(float(strategy.get("execution_delay_bars") or 1))
    if delay < 1:
        raise ValueError("next_bar execution requires execution_delay_bars >= 1")
    return delay


def position_value_snapshot(
    request: TargetWeightInput,
    row: int,
    strategy: Mapping[str, Any],
    positions: Mapping[str, float],
) -> tuple[dict[str, float], dict[str, float] | None]:
    """Return notional and optional margin-occupied values for positions."""
    notional = {
        instrument: float(quantity) * valuation_price(request, row, instrument)
        for instrument, quantity in positions.items()
    }
    if str(strategy.get("margin_mode") or "none") == "none":
        return notional, None
    margin = {}
    for position, instrument in enumerate(request.instruments):
        quantity = float(positions.get(instrument, 0.0))
        margin[instrument] = (
            abs(quantity)
            * valuation_price(request, row, instrument)
            * float(request.margin_ratios[row][position])
        )
    return notional, margin


def execution_price(
    base_price: float,
    signed_quantity: float,
    strategy: Mapping[str, Any],
) -> float:
    mode = str(strategy.get("slippage_mode") or "none")
    if mode == "none":
        return float(base_price)
    if mode == "fixed_bps":
        bps = float(strategy.get("slippage_bps") or 0.0)
        return float(base_price) * (1.0 + np.sign(signed_quantity) * bps / 10_000.0)
    raise ValueError(f"unsupported slippage mode: {mode}")


def capacity_limited_deltas(
    request: TargetWeightInput,
    row: int,
    strategy: Mapping[str, Any],
    desired: Mapping[str, float],
    current: Mapping[str, float],
) -> dict[str, float]:
    deltas = {
        instrument: float(desired.get(instrument, 0.0))
        - float(current.get(instrument, 0.0))
        for instrument in request.instruments
    }
    mode = str(strategy.get("liquidity_mode") or "infinite")
    if mode == "infinite":
        return deltas
    if mode != "volume_participation" or request.volumes is None:
        raise ValueError(f"unsupported or unavailable liquidity mode: {mode}")
    rate = float(strategy.get("participation_rate") or 0.0)
    if not 0 < rate <= 1:
        raise ValueError("participation_rate must be within (0, 1]")
    return {
        instrument: np.sign(delta) * min(
            abs(delta), request.volumes[instrument][row] * rate
        )
        for instrument, delta in deltas.items()
    }


def execution_trace_entry(
    request: TargetWeightInput,
    row: int,
    strategy: Mapping[str, Any],
    current: Mapping[str, float],
    deltas: Mapping[str, float],
    cash: float,
) -> dict[str, Any]:
    """Describe the fee-aware executable target produced inside one event.

    Emits the compact ``changed_only`` shape: only instruments actually moved
    by the event are listed. This mirrors the native event runner's vectorized
    trace so the detailed trace is identical across every engine, and keeps
    snapshot overlays free of a full copy of every unchanged instrument.
    """
    def clean(value: float) -> float:
        value = float(value)
        if abs(value) <= 1e-12:
            return 0.0
        return round(value, 10)

    fee_rate = float(strategy.get("fee_rate") or 0.0)
    sell_proceeds_after_fee = 0.0
    buy_cost_with_fee = 0.0
    delta_out: dict[str, float] = {}
    current_size: dict[str, float] = {}
    target_size: dict[str, float] = {}
    fill_price: dict[str, float] = {}
    notional: dict[str, float] = {}
    for instrument in request.instruments:
        delta = float(deltas.get(instrument, 0.0))
        if abs(delta) <= 1e-12:
            continue
        before = float(current.get(instrument, 0.0))
        price = execution_price(valuation_price(request, row, instrument), delta, strategy)
        trade_value = abs(delta) * price
        delta_out[instrument] = clean(delta)
        current_size[instrument] = clean(before)
        target_size[instrument] = clean(before + delta)
        fill_price[instrument] = clean(price)
        notional[instrument] = clean(trade_value)
        if delta < 0:
            sell_proceeds_after_fee += trade_value * (1.0 - fee_rate)
        else:
            buy_cost_with_fee += trade_value * (1.0 + fee_rate)
    return {
        "delta": delta_out,
        "current_size": current_size,
        "target_size": target_size,
        "fill_price": fill_price,
        "notional": notional,
        "cash_before": clean(cash),
        "cash_available_after_sells": clean(float(cash) + sell_proceeds_after_fee),
        "buy_cost_with_fee": clean(buy_cost_with_fee),
        "fee_rate": clean(fee_rate),
        "trace_shape": "changed_only",
    }


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


def parse_group_strategy_input(
    payload: Mapping[str, Any],
) -> tuple[TargetWeightInput, np.ndarray, np.ndarray, tuple[GroupTargetCalculator, ...]]:
    """Parse raw membership without calculating any framework targets."""

    configs = tuple(payload.get("strategy_configs", ()))
    request = parse_target_weight_input({**dict(payload), "strategies": configs})
    membership = np.asarray(payload.get("membership"), dtype=bool)
    if membership.ndim != 3 or membership.shape[0] != len(
        request.timestamps
    ) or membership.shape[2] != len(request.instruments):
        raise ValueError("membership must have timestamp, source-group, and instrument axes")
    if payload.get("signal_updates") is None:
        raise ValueError("group strategy requires an explicit signal-update mask")
    signal_updates = np.asarray(payload["signal_updates"], dtype=bool)
    if signal_updates.shape != membership.shape[:2]:
        raise ValueError("signal-update mask must match membership time/source-group axes")
    calculators = tuple(
        GroupTargetCalculator(
            request.instruments,
            {**dict(config), "membership_index": config.get("membership_index", position)},
        )
        for position, config in enumerate(configs)
    )
    return request, membership, signal_updates, calculators


def market_rule_diagnostics(payload: Mapping[str, Any]) -> dict[str, Any]:
    provenance = (payload.get("market_rules") or {}).get("provenance") or {}
    approximation_count = sum(
        int(counts.get("as_of_latest", 0))
        + int(counts.get("configured_default", 0))
        for counts in provenance.values()
    )
    return {
        "market_rule_approximation_count": approximation_count,
        "market_rule_provenance": provenance,
    }


def setting_fallback_diagnostics(strategy: Mapping[str, Any]) -> dict[str, Any]:
    fallbacks = strategy.get("_setting_fallbacks") or []
    if not isinstance(fallbacks, list) or not fallbacks:
        return {}
    return {
        "setting_fallback_count": len(fallbacks),
        "setting_fallbacks": fallbacks,
    }
