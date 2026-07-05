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
    execution_delay_bars,
    execution_trace_entry,
    execution_price,
    execution_timing,
    parse_group_strategy_input,
    parse_target_weight_input,
    position_value_snapshot,
    require_worker_execution_policies,
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


def run_strategy_intents(payload: Mapping[str, Any], progress=None) -> dict[str, Any]:
    """Event-driven strategy-intent replay through Zipline's Ledger transaction lifecycle.

    Per bar: mark positions to market on Zipline's PositionTracker, execute
    due targets as Zipline Transactions processed by its Ledger (fees via
    process_commission), then compute this bar's target via the group
    calculator and schedule it for the next bar — target on SIGNAL, fill on
    the following ORDER, matching ADR-029's event order. Broker policy
    selectors (ADR-028) are validated up front; cash rescale + lot floor
    (cash_policy=rescale_buy_orders, min_lot_policy=floor_to_lot) run in
    _zipline_executable_deltas before transactions are created.
    """
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
    total_replay_steps = len(request.timestamps) * len(request.strategies)
    for strategy_position, (strategy, calculator) in enumerate(
        zip(request.strategies, calculators, strict=True)
    ):
        require_worker_execution_policies(
            strategy,
            engine="zipline",
            supported={"fill_cap_policy": frozenset({"no_cap", "volume_participation"})},
        )
        strategy_cash = float(strategy.get("initial_capital") or request.initial_cash)
        ledger = Ledger(request.timestamps, strategy_cash, "daily")
        timing = execution_timing(strategy)
        delay_bars = execution_delay_bars(strategy)
        pending_deltas: list[tuple[int, dict[str, float]]] = []
        transaction_number = 0
        equity_curve = {}
        position_curve = {}
        notional_curve = {}
        margin_curve = {}
        execution_trace = {}
        execution_trace_count = 0
        collect_trace = bool(strategy.get("collect_execution_trace"))

        def _positions() -> dict[str, float]:
            return {
                instrument: float(
                    ledger.position_tracker.positions[asset].amount
                    if asset in ledger.position_tracker.positions else 0.0
                )
                for instrument, asset in assets.items()
            }

        def _deltas_for_target(row: int, target) -> dict[str, float]:
            ledger._dirty_portfolio = True
            value = float(ledger.portfolio.portfolio_value)
            desired = target_quantities(request, row, target, value, strategy)
            current = _positions()
            return _zipline_executable_deltas(
                request, row, strategy, desired, current, float(ledger.portfolio.cash),
            )

        def _execute(row: int, timestamp, deltas: Mapping[str, float]) -> None:
            nonlocal transaction_number, execution_trace_count
            ledger._dirty_portfolio = True
            current = _positions()
            executable = _zipline_executable_deltas(
                request,
                row,
                strategy,
                {
                    instrument: float(current.get(instrument, 0.0)) + float(deltas.get(instrument, 0.0))
                    for instrument in request.instruments
                },
                current,
                float(ledger.portfolio.cash),
            )
            if any(abs(delta) > 1e-12 for delta in executable.values()):
                execution_trace_count += 1
                if collect_trace:
                    execution_trace[timestamp.isoformat()] = execution_trace_entry(
                        request, row, strategy, current, executable,
                        float(ledger.portfolio.cash),
                    )
            for sell_first in (True, False):
                for instrument, delta in executable.items():
                    if abs(delta) <= 1e-12 or (delta < 0) != sell_first:
                        continue
                    transaction_number += 1
                    fill_price = execution_price(
                        valuation_price(request, row, instrument), delta, strategy
                    )
                    ledger.process_transaction(Transaction(
                        assets[instrument], delta, timestamp, fill_price,
                        f"order-{transaction_number}",
                    ))
                    fee = abs(delta) * fill_price * float(strategy.get("fee_rate") or 0.0)
                    if fee:
                        ledger.process_commission({"asset": assets[instrument], "cost": fee})

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
            due_deltas = [deltas for due_row, deltas in pending_deltas if due_row <= row]
            pending_deltas = [
                (due_row, deltas) for due_row, deltas in pending_deltas if due_row > row
            ]
            for pending in due_deltas:
                _execute(row, timestamp, pending)
            target = calculator.update(
                timestamp,
                np.asarray([request.prices[name][row] for name in request.instruments]),
                memberships[row],
                updates[row],
                np.asarray(request.margin_ratios[row]),
            )
            if target is not None:
                deltas = _deltas_for_target(row, target)
                if timing == "same_bar":
                    _execute(row, timestamp, deltas)
                else:
                    pending_deltas.append((row + delay_bars, deltas))
            ledger._dirty_portfolio = True
            equity_curve[timestamp.isoformat()] = float(ledger.portfolio.portfolio_value)
            positions_row = _positions()
            position_curve[timestamp.isoformat()] = positions_row
            notional_values, margin_values = position_value_snapshot(
                request, row, strategy, positions_row
            )
            notional_curve[timestamp.isoformat()] = notional_values
            if margin_values is not None:
                margin_curve[timestamp.isoformat()] = margin_values
            if progress is not None and should_report_progress(
                strategy_position * len(request.timestamps) + row + 1, total_replay_steps,
            ):
                progress(
                    strategy_position * len(request.timestamps) + row + 1,
                    total_replay_steps,
                    timestamp,
                )
        ledger._dirty_portfolio = True
        portfolios[calculator.strategy_id] = {
            "initial_value": strategy_cash,
            "final_value": float(ledger.portfolio.portfolio_value),
            "positions": _positions(),
            "equity_curve": equity_curve,
            "position_curve": position_curve,
            "notional_curve": notional_curve,
            "margin_curve": margin_curve,
            "execution_trace": execution_trace,
            "execution_trace_count": execution_trace_count,
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
        "event_count": len(request.timestamps),
        "signal_kind": payload.get("signal_kind"),
    }


def run_group_strategy(payload: Mapping[str, Any], progress=None) -> dict[str, Any]:
    return run_strategy_intents(payload, progress=progress)


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
