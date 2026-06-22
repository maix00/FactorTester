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
    execute_target_weights,
    execution_trace_entry,
    execution_delay_bars,
    execution_timing,
    market_rule_diagnostics,
    parse_group_strategy_input,
    parse_target_weight_input,
    portfolio_value,
    position_value_snapshot,
    setting_fallback_diagnostics,
    should_report_progress,
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
        pending_targets = []
        equity_curve = {}
        position_curve = {}
        notional_curve = {}
        margin_curve = {}
        execution_trace = {}
        timing = execution_timing(strategy)
        delay_bars = execution_delay_bars(strategy)
        for row, timestamp in enumerate(request.timestamps):
            current_value = portfolio_value(request, row, positions, cash)
            due_targets = [target for due_row, target in pending_targets if due_row <= row]
            pending_targets = [
                (due_row, target) for due_row, target in pending_targets if due_row > row
            ]
            for pending in due_targets:
                deltas_before = dict(positions)
                cash_before = cash
                cash, positions, deltas = execute_target_weights(
                    request, row, strategy, pending, positions, cash
                )
                if any(abs(delta) > 1e-12 for delta in deltas.values()):
                    execution_trace[timestamp.isoformat()] = execution_trace_entry(
                        request, row, strategy, deltas_before, deltas, cash_before
                )
                current_value = portfolio_value(request, row, positions, cash)
            target = calculator.update(
                timestamp,
                np.asarray([
                    request.prices[name][row] for name in request.instruments
                ]),
                memberships[row],
                updates[row],
                np.asarray(request.margin_ratios[row]),
            )
            if timing == "same_bar" and target is not None:
                deltas_before = dict(positions)
                cash_before = cash
                cash, positions, deltas = execute_target_weights(
                    request, row, strategy, target, positions, cash
                )
                if any(abs(delta) > 1e-12 for delta in deltas.values()):
                    execution_trace[timestamp.isoformat()] = execution_trace_entry(
                        request, row, strategy, deltas_before, deltas, cash_before
                    )
                current_value = portfolio_value(request, row, positions, cash)
            elif timing == "next_bar":
                if target is not None:
                    pending_targets.append((row + delay_bars, target))
            equity_curve[timestamp.isoformat()] = float(current_value)
            position_curve[timestamp.isoformat()] = dict(positions)
            notional_values, margin_values = position_value_snapshot(
                request, row, strategy, positions
            )
            notional_curve[timestamp.isoformat()] = notional_values
            if margin_values is not None:
                margin_curve[timestamp.isoformat()] = margin_values
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
