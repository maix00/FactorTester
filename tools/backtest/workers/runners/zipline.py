"""Zipline target-weight runner using its Ledger transaction lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from zipline.assets import Equity
from zipline.assets.exchange_info import ExchangeInfo
from zipline.finance.ledger import Ledger
from zipline.finance.transaction import Transaction

from .common import (
    market_rule_diagnostics,
    capacity_limited_deltas,
    execution_trace_entry,
    execution_price,
    parse_group_strategy_input,
    parse_target_weight_input,
    position_value_snapshot,
    setting_fallback_diagnostics,
    target_quantities,
    target_rows,
    valuation_price,
    should_report_progress,
)


def run_target_weights(payload: Mapping[str, Any]) -> dict[str, Any]:
    request = parse_target_weight_input(payload)
    exchange = ExchangeInfo("GTHT", "GTHT", "CN")
    assets = {
        instrument: Equity(
            index + 1,
            exchange,
            symbol=instrument,
            asset_name=instrument,
            start_date=request.timestamps[0],
            end_date=request.timestamps[-1],
        )
        for index, instrument in enumerate(request.instruments)
    }
    portfolios = {}
    for strategy in request.strategies:
        strategy_cash = float(strategy.get("initial_capital") or request.initial_cash)
        ledger = Ledger(request.timestamps, strategy_cash, "daily")
        targets = target_rows(strategy, request.timestamps)
        pending = None
        transaction_number = 0
        equity_curve = {}
        position_curve = {}
        for index, timestamp in enumerate(request.timestamps):
            current_prices = {
                instrument: valuation_price(request, index, instrument)
                for instrument in request.instruments
            }
            for instrument, asset in assets.items():
                ledger.position_tracker.update_position(
                    asset,
                    last_sale_price=current_prices[instrument],
                    last_sale_date=timestamp,
                )
            ledger._dirty_portfolio = True
            if pending is not None:
                value = float(ledger.portfolio.portfolio_value)
                desired = target_quantities(request, index, pending, value, strategy)
                deltas = _zipline_executable_deltas(
                    request,
                    index,
                    strategy,
                    desired,
                    {
                        instrument: (
                            ledger.position_tracker.positions[asset].amount
                            if asset in ledger.position_tracker.positions else 0.0
                        )
                        for instrument, asset in assets.items()
                    },
                    float(ledger.portfolio.cash),
                )
                for sell_first in (True, False):
                    for instrument, delta in deltas.items():
                        if abs(delta) <= 1e-12 or (delta < 0) != sell_first:
                            continue
                        transaction_number += 1
                        fill_price = execution_price(
                            current_prices[instrument], delta, strategy
                        )
                        ledger.process_transaction(Transaction(
                            assets[instrument],
                            delta,
                            timestamp,
                            fill_price,
                            f"order-{transaction_number}",
                        ))
                        fee = abs(delta) * fill_price * float(
                            strategy.get("fee_rate") or 0.0
                        )
                        if fee:
                            ledger.process_commission({"asset": assets[instrument], "cost": fee})
            ledger._dirty_portfolio = True
            equity_curve[timestamp.isoformat()] = float(ledger.portfolio.portfolio_value)
            position_curve[timestamp.isoformat()] = {
                instrument: float(
                    ledger.position_tracker.positions[asset].amount
                    if asset in ledger.position_tracker.positions else 0.0
                )
                for instrument, asset in assets.items()
            }
            next_target = targets.get(timestamp)
            pending = next_target
        portfolio = ledger.portfolio
        portfolios[strategy["strategy_id"]] = {
            "initial_value": strategy_cash,
            "final_value": float(portfolio.portfolio_value),
            "positions": {
                instrument: float(
                    ledger.position_tracker.positions[asset].amount
                    if asset in ledger.position_tracker.positions else 0.0
                )
                for instrument, asset in assets.items()
            },
            "equity_curve": equity_curve,
            "position_curve": position_curve,
        }
    return {"engine": "zipline", "portfolios": portfolios}


def run_group_strategy(payload: Mapping[str, Any], progress=None) -> dict[str, Any]:
    request, memberships, updates, calculators = parse_group_strategy_input(payload)
    exchange = ExchangeInfo("GTHT", "GTHT", "CN")
    assets = {
        instrument: Equity(
            index + 1,
            exchange,
            symbol=instrument,
            asset_name=instrument,
            start_date=request.timestamps[0],
            end_date=request.timestamps[-1],
        )
        for index, instrument in enumerate(request.instruments)
    }
    portfolios = {}
    for strategy_position, (strategy, calculator) in enumerate(
        zip(request.strategies, calculators, strict=True)
    ):
        strategy_cash = float(strategy.get("initial_capital") or request.initial_cash)
        ledger = Ledger(request.timestamps, strategy_cash, "daily")
        pending = None
        transaction_number = 0
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
            for instrument, asset in assets.items():
                ledger.position_tracker.update_position(
                    asset,
                    last_sale_price=current_prices[instrument],
                    last_sale_date=timestamp,
                )
            ledger._dirty_portfolio = True
            if pending is not None:
                desired = target_quantities(
                    request,
                    row,
                    pending,
                    float(ledger.portfolio.portfolio_value),
                    strategy,
                )
                deltas = _zipline_executable_deltas(
                    request,
                    row,
                    strategy,
                    desired,
                    {
                        instrument: ledger.position_tracker.positions[asset].amount
                        for instrument, asset in assets.items()
                    },
                    float(ledger.portfolio.cash),
                )
                current_positions = {
                    instrument: (
                        ledger.position_tracker.positions[asset].amount
                        if asset in ledger.position_tracker.positions else 0.0
                    )
                    for instrument, asset in assets.items()
                }
                execution_trace[timestamp.isoformat()] = execution_trace_entry(
                    request,
                    row,
                    strategy,
                    current_positions,
                    deltas,
                    float(ledger.portfolio.cash),
                )
                for sell_first in (True, False):
                    for instrument, delta in deltas.items():
                        if abs(delta) <= 1e-12 or (delta < 0) != sell_first:
                            continue
                        transaction_number += 1
                        fill_price = execution_price(
                            current_prices[instrument], delta, strategy
                        )
                        ledger.process_transaction(Transaction(
                            assets[instrument],
                            delta,
                            timestamp,
                            fill_price,
                            f"order-{transaction_number}",
                        ))
                        fee = abs(delta) * fill_price * float(
                            strategy.get("fee_rate") or 0.0
                        )
                        if fee:
                            ledger.process_commission({"asset": assets[instrument], "cost": fee})
            ledger._dirty_portfolio = True
            equity_curve[timestamp.isoformat()] = float(ledger.portfolio.portfolio_value)
            position_curve[timestamp.isoformat()] = {
                instrument: float(
                    ledger.position_tracker.positions[asset].amount
                    if asset in ledger.position_tracker.positions else 0.0
                )
                for instrument, asset in assets.items()
            }
            notional_values, margin_values = position_value_snapshot(
                request, row, strategy, position_curve[timestamp.isoformat()]
            )
            notional_curve[timestamp.isoformat()] = notional_values
            if margin_values is not None:
                margin_curve[timestamp.isoformat()] = margin_values
            pending = calculator.update(
                timestamp,
                np.asarray([request.prices[name][row] for name in request.instruments]),
                memberships[row],
                updates[row],
                np.asarray(request.margin_ratios[row]),
            )
            if (
                progress is not None
                and strategy_position == 0
                and should_report_progress(row + 1, len(request.timestamps))
            ):
                progress(row + 1, len(request.timestamps), timestamp)
        portfolio = ledger.portfolio
        portfolios[calculator.strategy_id] = {
            "initial_value": strategy_cash,
            "final_value": float(portfolio.portfolio_value),
            "positions": {
                instrument: float(
                    ledger.position_tracker.positions[asset].amount
                    if asset in ledger.position_tracker.positions else 0.0
                )
                for instrument, asset in assets.items()
            },
            "equity_curve": equity_curve,
            "position_curve": position_curve,
            "notional_curve": notional_curve,
            "margin_curve": margin_curve,
            "execution_trace": execution_trace,
        }
    return {
        "engine": "zipline",
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
    }


def _zipline_executable_deltas(
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
    for position_index, instrument in enumerate(request.instruments):
        delta = adjusted.get(instrument, 0.0)
        if delta <= 0:
            continue
        lot_size = request.lot_sizes[row][position_index]
        adjusted[instrument] = float(
            int((delta * scale) / lot_size + 1e-12) * lot_size
        )
    return adjusted
