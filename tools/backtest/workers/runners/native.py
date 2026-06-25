"""Native event-runtime runner for raw group strategy inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from ...event_driven.backtest import BacktestRunner, ExecutionVenue, StrategyLane
from ...event_driven.contracts import BacktestPlan, RunIdentity
from ...event_driven.runtime import EventTopic, MarketSlice, ProductPrice, ReplayEventSource
from ...execution.fees import ProviderCommissionModel
from ...execution.trading import (
    CashAccounting,
    Ledger,
    MarketState,
    NextBarBroker,
    OrderManager,
    ProviderContractSizer,
)
from ...factors.events import PrecomputedFactorPublisher
from ...market_rules import (
    ContractRule,
    FeeSchedule,
    RuleFallbackPolicy,
    RuleUsageJournal,
    TemporalRuleProvider,
)
from ...risk.margin import FuturesMarginConstraint
from ...strategies.membership import MembershipAllocationStrategy
from ...strategies.allocation import TrailingVolatilityEstimator
from .common import (
    execution_delay_bars,
    execution_timing,
    market_rule_diagnostics,
    parse_group_strategy_input,
    parse_target_weight_input,
    portfolio_value,
    setting_fallback_diagnostics,
    should_report_progress,
    valuation_price,
)


def _positions_dict(instruments: tuple[str, ...], positions: np.ndarray) -> dict[str, float]:
    return {
        instrument: float(positions[index])
        for index, instrument in enumerate(instruments)
    }


def _target_vector(instruments: tuple[str, ...], target: Mapping[str, float]) -> np.ndarray:
    values = np.zeros(len(instruments), dtype=float)
    for index, instrument in enumerate(instruments):
        values[index] = float(target.get(instrument, 0.0))
    return values


def _execution_price_vector(base_prices: np.ndarray, deltas: np.ndarray, strategy: Mapping[str, Any]) -> np.ndarray:
    mode = str(strategy.get("slippage_mode") or "none")
    if mode == "none":
        return base_prices
    if mode == "fixed_bps":
        bps = float(strategy.get("slippage_bps") or 0.0)
        return base_prices * (1.0 + np.sign(deltas) * bps / 10_000.0)
    raise ValueError(f"unsupported slippage mode: {mode}")


def _position_value_snapshot_vector(
    request,
    row: int,
    strategy: Mapping[str, Any],
    positions: np.ndarray,
    valuation_values: np.ndarray,
    margin_ratios: np.ndarray,
) -> tuple[dict[str, float], dict[str, float] | None]:
    active = np.flatnonzero(np.abs(positions) > 1e-12)
    notional = {
        request.instruments[int(index)]: float(positions[index] * valuation_values[index])
        for index in active
    }
    if str(strategy.get("margin_mode") or "none") == "none":
        return notional, None
    margin = {
        request.instruments[int(index)]: float(abs(positions[index]) * valuation_values[index] * margin_ratios[index])
        for index in active
    }
    return notional, margin


def _execute_target_weights_vector(
    request,
    row: int,
    strategy: Mapping[str, Any],
    target: Mapping[str, float],
    positions: np.ndarray,
    cash: float,
    current_value: float,
    valuation_values: np.ndarray,
    volumes_row: np.ndarray | None,
) -> tuple[float, np.ndarray, np.ndarray]:
    weights = _target_vector(request.instruments, target)
    if str(strategy.get("margin_mode") or "none") != "none":
        collateral = float(strategy.get("collateral_fraction") or 1.0)
        required = float(np.sum(np.abs(weights) * np.asarray(request.margin_ratios[row], dtype=float)))
        if required > collateral + 1e-12:
            weights = weights * (collateral / required)

    prices = np.asarray([request.prices[name][row] for name in request.instruments], dtype=float)
    multipliers = np.asarray(request.multipliers[row], dtype=float)
    lot_sizes = np.asarray(request.lot_sizes[row], dtype=float)
    raw = np.abs(weights) * float(current_value) / (prices * multipliers)
    desired = np.sign(weights) * np.floor(raw / lot_sizes + 1e-12) * lot_sizes
    deltas = desired - positions

    liquidity_mode = str(strategy.get("liquidity_mode") or "infinite")
    if liquidity_mode != "infinite":
        if liquidity_mode != "volume_participation" or volumes_row is None:
            raise ValueError(f"unsupported or unavailable liquidity mode: {liquidity_mode}")
        rate = float(strategy.get("participation_rate") or 0.0)
        if not 0 < rate <= 1:
            raise ValueError("participation_rate must be within (0, 1]")
        capacity = np.asarray(volumes_row, dtype=float) * rate
        deltas = np.sign(deltas) * np.minimum(np.abs(deltas), capacity)

    fee_rate = float(strategy.get("fee_rate") or 0.0)
    fill_prices = _execution_price_vector(valuation_values, deltas, strategy)
    trade_values = np.abs(deltas) * fill_prices
    sells = deltas < -1e-12
    buys = deltas > 1e-12
    available = float(cash) + float(np.sum(trade_values[sells] * (1.0 - fee_rate)))
    buy_cost = float(np.sum(trade_values[buys] * (1.0 + fee_rate)))
    if buy_cost > max(available, 0.0) + 1e-9:
        if buy_cost <= 0.0 or available <= 0.0:
            deltas = np.where(deltas < 0, deltas, 0.0)
        else:
            scale = available / buy_cost
            buy_scaled = np.floor((deltas * scale) / lot_sizes + 1e-12) * lot_sizes
            deltas = np.where(deltas > 0, buy_scaled, deltas)
            fill_prices = _execution_price_vector(valuation_values, deltas, strategy)
            trade_values = np.abs(deltas) * fill_prices

    next_cash = float(cash) - float(np.sum(deltas * fill_prices + trade_values * fee_rate))
    next_positions = positions + deltas
    return next_cash, next_positions, deltas


def _execution_trace_entry_vector(
    request,
    row: int,
    strategy: Mapping[str, Any],
    current: np.ndarray,
    deltas: np.ndarray,
    cash: float,
    valuation_values: np.ndarray,
) -> dict[str, Any]:
    """Compact trace for the instruments changed by one event.

    Snapshot overlays need the actionable event delta, not a full sparse copy
    of every unchanged instrument on every fill.
    """
    changed = np.flatnonzero(np.abs(deltas) > 1e-12)

    def clean(value: float) -> float:
        value = float(value)
        if abs(value) <= 1e-12:
            return 0.0
        return round(value, 10)

    fee_rate = float(strategy.get("fee_rate") or 0.0)
    fill_prices = _execution_price_vector(valuation_values, deltas, strategy)
    changed_deltas = deltas[changed]
    changed_prices = fill_prices[changed]
    trade_values = np.abs(changed_deltas) * changed_prices
    sell_mask = changed_deltas < -1e-12
    buy_mask = changed_deltas > 1e-12
    sell_proceeds_after_fee = float(np.sum(trade_values[sell_mask] * (1.0 - fee_rate)))
    buy_cost_with_fee = float(np.sum(trade_values[buy_mask] * (1.0 + fee_rate)))

    delta: dict[str, float] = {}
    current_size: dict[str, float] = {}
    target_size: dict[str, float] = {}
    fill_price: dict[str, float] = {}
    notional: dict[str, float] = {}
    for index, price, trade_value in zip(changed, changed_prices, trade_values, strict=True):
        instrument = request.instruments[int(index)]
        delta[instrument] = clean(deltas[index])
        current_size[instrument] = clean(current[index])
        target_size[instrument] = clean(current[index] + deltas[index])
        fill_price[instrument] = clean(price)
        notional[instrument] = clean(trade_value)
    return {
        "delta": delta,
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


def run_group_strategy(payload: Mapping[str, Any], progress=None) -> dict[str, Any]:
    request, memberships, updates, calculators = parse_group_strategy_input(payload)
    strategy_states: list[dict[str, Any]] = []
    volatility_estimators: dict[tuple[int, int, float], TrailingVolatilityEstimator] = {}
    volatility_previous_prices: dict[tuple[int, int, float], np.ndarray | None] = {}
    for strategy, calculator in zip(request.strategies, calculators, strict=True):
        strategy_cash = float(strategy.get("initial_capital") or request.initial_cash)
        volatility_key = None
        if getattr(calculator, "allocation_name", "") == "inverse_volatility":
            estimator = calculator.estimator
            volatility_key = (
                int(estimator.lookback),
                int(estimator.min_observations),
                float(estimator.annualization),
            )
            if volatility_key not in volatility_estimators:
                volatility_estimators[volatility_key] = TrailingVolatilityEstimator(
                    tuple(request.instruments),
                    lookback=volatility_key[0],
                    min_observations=volatility_key[1],
                    annualization=volatility_key[2],
                )
                volatility_previous_prices[volatility_key] = None
        strategy_states.append({
            "strategy": strategy,
            "calculator": calculator,
            "volatility_key": volatility_key,
            "initial_value": strategy_cash,
            "cash": strategy_cash,
            "positions": np.zeros(len(request.instruments), dtype=float),
            "pending_targets": [],
            "equity_curve": {},
            "position_curve": {},
            "notional_curve": {},
            "margin_curve": {},
            "execution_trace": {},
            "execution_trace_count": 0,
            "timing": execution_timing(strategy),
            "delay_bars": execution_delay_bars(strategy),
            "collect_execution_trace": bool(strategy.get("collect_execution_trace")),
        })

    total_replay_steps = len(request.timestamps)
    for row, timestamp in enumerate(request.timestamps):
        current_prices = np.asarray([
            request.prices[name][row] for name in request.instruments
        ])
        valuation_values = current_prices * np.asarray(request.multipliers[row], dtype=float)
        volumes_row = (
            np.asarray([request.volumes[name][row] for name in request.instruments], dtype=float)
            if request.volumes is not None else None
        )
        margin_ratios = np.asarray(request.margin_ratios[row])
        volatility_snapshots: dict[tuple[int, int, float], dict[str, float]] = {}
        for key, estimator in volatility_estimators.items():
            previous = volatility_previous_prices.get(key)
            if previous is not None:
                with np.errstate(all="ignore"):
                    returns = current_prices / previous - 1.0
                estimator.update_values(returns)
            volatility_previous_prices[key] = current_prices.copy()
            volatility_snapshots[key] = estimator.snapshot()
        for state in strategy_states:
            strategy = state["strategy"]
            calculator = state["calculator"]
            positions = state["positions"]
            cash = float(state["cash"])
            pending_targets = state["pending_targets"]
            current_value = float(cash + np.sum(positions * valuation_values))
            due_targets = [target for due_row, target in pending_targets if due_row <= row]
            state["pending_targets"] = [
                (due_row, target) for due_row, target in pending_targets if due_row > row
            ]
            for pending in due_targets:
                deltas_before_vec = positions.copy() if state["collect_execution_trace"] else None
                cash_before = cash
                cash, positions, deltas_vec = _execute_target_weights_vector(
                    request, row, strategy, pending, positions, cash, current_value,
                    valuation_values, volumes_row,
                )
                if bool(np.any(np.abs(deltas_vec) > 1e-12)):
                    state["execution_trace_count"] += 1
                    if state["collect_execution_trace"]:
                        state["execution_trace"][timestamp.isoformat()] = _execution_trace_entry_vector(
                            request, row, strategy, deltas_before_vec, deltas_vec, cash_before,
                            valuation_values,
                        )
                current_value = float(cash + np.sum(positions * valuation_values))
            target = calculator.update(
                timestamp,
                current_prices,
                memberships[row],
                updates[row],
                margin_ratios,
                volatility_snapshots.get(state["volatility_key"]),
            )
            if state["timing"] == "same_bar" and target is not None:
                deltas_before_vec = positions.copy() if state["collect_execution_trace"] else None
                cash_before = cash
                cash, positions, deltas_vec = _execute_target_weights_vector(
                    request, row, strategy, target, positions, cash, current_value,
                    valuation_values, volumes_row,
                )
                if bool(np.any(np.abs(deltas_vec) > 1e-12)):
                    state["execution_trace_count"] += 1
                    if state["collect_execution_trace"]:
                        state["execution_trace"][timestamp.isoformat()] = _execution_trace_entry_vector(
                            request, row, strategy, deltas_before_vec, deltas_vec, cash_before,
                            valuation_values,
                        )
                current_value = float(cash + np.sum(positions * valuation_values))
            elif state["timing"] == "next_bar":
                if target is not None:
                    state["pending_targets"].append((row + state["delay_bars"], target))
            state["cash"] = cash
            state["positions"] = positions
            state["equity_curve"][timestamp.isoformat()] = float(current_value)
            state["position_curve"][timestamp.isoformat()] = _positions_dict(request.instruments, positions)
            notional_values, margin_values = _position_value_snapshot_vector(
                request, row, strategy, positions, valuation_values, margin_ratios
            )
            state["notional_curve"][timestamp.isoformat()] = notional_values
            if margin_values is not None:
                state["margin_curve"][timestamp.isoformat()] = margin_values
        if progress is not None and should_report_progress(row + 1, total_replay_steps):
            progress(row + 1, total_replay_steps, timestamp)

    portfolios = {}
    for state in strategy_states:
        calculator = state["calculator"]
        cash = float(state["cash"])
        positions = state["positions"]
        positions_dict = _positions_dict(request.instruments, positions)
        final_prices = np.asarray([
            valuation_price(request, len(request.timestamps) - 1, instrument)
            for instrument in request.instruments
        ], dtype=float)
        portfolios[calculator.strategy_id] = {
            "initial_value": state["initial_value"],
            "final_value": float(cash + np.sum(positions * final_prices)),
            "positions": positions_dict,
            "equity_curve": state["equity_curve"],
            "position_curve": state["position_curve"],
            "notional_curve": state["notional_curve"],
            "margin_curve": state["margin_curve"],
            "execution_trace": state["execution_trace"],
            "execution_trace_count": state["execution_trace_count"],
        }
    return {
        "engine": "native",
        "portfolios": portfolios,
        "target_trace": {item.strategy_id: item.target_trace for item in calculators},
        "execution_trace": {
            strategy_id: portfolio.get("execution_trace", {})
            for strategy_id, portfolio in portfolios.items()
        },
        "strategy_diagnostics": {
            item.strategy_id: {
                **item.diagnostics,
                **market_rule_diagnostics(payload),
                **setting_fallback_diagnostics(strategy),
            }
            for item, strategy in zip(calculators, request.strategies, strict=True)
        },
        "event_count": len(request.timestamps),
    }
