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
from .common import (
    capacity_limited_deltas,
    execution_trace_entry,
    execution_price,
    market_rule_diagnostics,
    parse_group_strategy_input,
    parse_target_weight_input,
    position_value_snapshot,
    setting_fallback_diagnostics,
    should_report_progress,
    target_quantities,
    valuation_price,
)


def run_group_strategy(payload: Mapping[str, Any], progress=None) -> dict[str, Any]:
    request, memberships, updates, calculators = parse_group_strategy_input(payload)
    portfolios = {}
    total_replay_steps = len(request.timestamps) * len(request.strategies)
    for strategy_position, (strategy, calculator) in enumerate(
        zip(request.strategies, calculators, strict=True)
    ):
        strategy_cash = float(strategy.get("initial_capital") or request.initial_cash)
        cash = strategy_cash
        positions = {instrument: 0.0 for instrument in request.instruments}
        pending = None
        equity_curve = {}
        position_curve = {}
        notional_curve = {}
        margin_curve = {}
        execution_trace = {}
        for row, timestamp in enumerate(request.timestamps):
            current_prices = {
                instrument: valuation_price(request, row, instrument)
                for instrument in request.instruments
            }
            portfolio_value = cash + sum(
                positions[instrument] * current_prices[instrument]
                for instrument in request.instruments
            )
            if pending is not None:
                desired = target_quantities(
                    request, row, pending, portfolio_value, strategy
                )
                deltas = _native_executable_deltas(
                    request,
                    row,
                    strategy,
                    desired,
                    positions,
                    cash,
                )
                if any(abs(delta) > 1e-12 for delta in deltas.values()):
                    execution_trace[timestamp.isoformat()] = execution_trace_entry(
                        request, row, strategy, positions, deltas, cash
                    )
                for sell_first in (True, False):
                    for instrument, delta in deltas.items():
                        if abs(delta) <= 1e-12 or (delta < 0) != sell_first:
                            continue
                        fill_price = execution_price(
                            current_prices[instrument], delta, strategy
                        )
                        trade_value = abs(delta) * fill_price
                        fee = trade_value * float(strategy.get("fee_rate") or 0.0)
                        cash -= delta * fill_price + fee
                        positions[instrument] += delta
                portfolio_value = cash + sum(
                    positions[instrument] * current_prices[instrument]
                    for instrument in request.instruments
                )
            equity_curve[timestamp.isoformat()] = float(portfolio_value)
            position_curve[timestamp.isoformat()] = dict(positions)
            notional_values, margin_values = position_value_snapshot(
                request, row, strategy, positions
            )
            notional_curve[timestamp.isoformat()] = notional_values
            if margin_values is not None:
                margin_curve[timestamp.isoformat()] = margin_values
            pending = calculator.update(
                timestamp,
                np.asarray([
                    request.prices[name][row] for name in request.instruments
                ]),
                memberships[row],
                updates[row],
                np.asarray(request.margin_ratios[row]),
            )
            if (
                progress is not None
                and should_report_progress(
                    strategy_position * len(request.timestamps) + row + 1,
                    total_replay_steps,
                )
            ):
                progress(
                    strategy_position * len(request.timestamps) + row + 1,
                    total_replay_steps,
                    timestamp,
                )
        portfolios[calculator.strategy_id] = {
            "initial_value": strategy_cash,
            "final_value": float(
                cash + sum(
                    positions[instrument]
                    * valuation_price(request, len(request.timestamps) - 1, instrument)
                    for instrument in request.instruments
                )
            ),
            "positions": positions,
            "equity_curve": equity_curve,
            "position_curve": position_curve,
            "notional_curve": notional_curve,
            "margin_curve": margin_curve,
            "execution_trace": execution_trace,
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


def _native_executable_deltas(
    request,
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
