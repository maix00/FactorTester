"""Qlib target-weight runner using Qlib's Position and Order lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from qlib.backtest.decision import Order
from qlib.backtest.position import Position

from .common import (
    market_rule_diagnostics,
    capacity_limited_deltas,
    execute_target_weights,
    execution_delay_bars,
    execution_price,
    execution_trace_entry,
    execution_timing,
    parse_group_strategy_input,
    parse_target_weight_input,
    portfolio_value,
    position_value_snapshot,
    setting_fallback_diagnostics,
    target_quantities,
    target_rows,
    valuation_price,
    should_report_progress,
)


class _SignedPosition(Position):
    """Qlib Position extension that preserves its ledger API while allowing shorts."""

    def _sell_stock(
        self, stock_id: str, trade_val: float, cost: float, trade_price: float
    ) -> None:
        trade_amount = trade_val / trade_price
        if stock_id not in self.position:
            self._init_stock(stock_id, -trade_amount, trade_price)
        else:
            self.position[stock_id]["amount"] -= trade_amount
            if np.isclose(self.position[stock_id]["amount"], 0.0):
                self._del_stock(stock_id)
        self.position["cash"] += trade_val - cost


def run_target_weights(payload: Mapping[str, Any]) -> dict[str, Any]:
    request = parse_target_weight_input(payload)
    portfolios = {}
    for strategy in request.strategies:
        strategy_cash = float(strategy.get("initial_capital") or request.initial_cash)
        position = _SignedPosition(cash=strategy_cash)
        targets = target_rows(strategy, request.timestamps)
        pending = None
        equity_curve = {}
        position_curve = {}
        for index, timestamp in enumerate(request.timestamps):
            current_prices = {
                instrument: valuation_price(request, index, instrument)
                for instrument in request.instruments
            }
            for instrument in position.get_stock_list():
                position.update_stock_price(instrument, current_prices[instrument])
            if pending is not None:
                _rebalance(
                    position,
                    target_quantities(
                        request,
                        index,
                        pending,
                        float(position.calculate_value()),
                        strategy,
                    ),
                    current_prices,
                    timestamp,
                    fee_rate=float(strategy.get("fee_rate") or 0.0),
                    strategy=strategy,
                    request=request,
                    row=index,
                )
            equity_curve[timestamp.isoformat()] = float(position.calculate_value())
            position_curve[timestamp.isoformat()] = {
                instrument: float(position.get_stock_amount(instrument))
                for instrument in request.instruments
            }
            next_target = targets.get(timestamp)
            pending = next_target
        portfolios[strategy["strategy_id"]] = {
            "initial_value": strategy_cash,
            "final_value": float(position.calculate_value()),
            "positions": {
                instrument: float(position.get_stock_amount(instrument))
                for instrument in request.instruments
            },
            "equity_curve": equity_curve,
            "position_curve": position_curve,
        }
    return {"engine": "qlib", "portfolios": portfolios}


def run_group_strategy(payload: Mapping[str, Any], progress=None) -> dict[str, Any]:
    request, memberships, updates, calculators = parse_group_strategy_input(payload)
    portfolios = {}
    total_replay_steps = len(request.timestamps) * len(request.strategies)
    for strategy_position, (strategy, calculator) in enumerate(
        zip(request.strategies, calculators, strict=True)
    ):
        strategy_cash = float(strategy.get("initial_capital") or request.initial_cash)
        position = _SignedPosition(cash=strategy_cash)
        cash = strategy_cash
        positions = {instrument: 0.0 for instrument in request.instruments}
        pending_targets = []
        equity_curve = {}
        position_curve = {}
        notional_curve = {}
        margin_curve = {}
        execution_trace = {}
        execution_trace_count = 0
        collect_trace = bool(strategy.get("collect_execution_trace"))
        timing = execution_timing(strategy)
        delay_bars = execution_delay_bars(strategy)
        for row, timestamp in enumerate(request.timestamps):
            current_prices = {
                instrument: valuation_price(request, row, instrument)
                for instrument in request.instruments
            }
            for instrument in position.get_stock_list():
                position.update_stock_price(instrument, current_prices[instrument])
            due_targets = [target for due_row, target in pending_targets if due_row <= row]
            pending_targets = [
                (due_row, target) for due_row, target in pending_targets if due_row > row
            ]
            for pending in due_targets:
                before = dict(positions)
                cash_before = cash
                cash, positions, deltas = execute_target_weights(
                    request, row, strategy, pending, positions, cash
                )
                if any(abs(delta) > 1e-12 for delta in deltas.values()):
                    execution_trace_count += 1
                    if collect_trace:
                        execution_trace[timestamp.isoformat()] = execution_trace_entry(
                            request, row, strategy, before, deltas, cash_before
                        )
            target = calculator.update(
                timestamp,
                np.asarray([request.prices[name][row] for name in request.instruments]),
                memberships[row],
                updates[row],
                np.asarray(request.margin_ratios[row]),
            )
            if timing == "same_bar" and target is not None:
                before = dict(positions)
                cash_before = cash
                cash, positions, deltas = execute_target_weights(
                    request, row, strategy, target, positions, cash
                )
                if any(abs(delta) > 1e-12 for delta in deltas.values()):
                    execution_trace_count += 1
                    if collect_trace:
                        execution_trace[timestamp.isoformat()] = execution_trace_entry(
                            request, row, strategy, before, deltas, cash_before
                        )
            elif timing == "next_bar":
                if target is not None:
                    pending_targets.append((row + delay_bars, target))
            equity_curve[timestamp.isoformat()] = float(
                portfolio_value(request, row, positions, cash)
            )
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
            "final_value": float(portfolio_value(request, len(request.timestamps) - 1, positions, cash)),
            "positions": positions,
            "equity_curve": equity_curve,
            "position_curve": position_curve,
            "notional_curve": notional_curve,
            "margin_curve": margin_curve,
            "execution_trace": execution_trace,
            "execution_trace_count": execution_trace_count,
        }
    return {
        "engine": "qlib",
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


def _rebalance(
    position: Position,
    quantities: Mapping[str, float],
    prices: Mapping[str, float],
    timestamp,
    *,
    fee_rate: float,
    strategy: Mapping[str, Any],
    request=None,
    row: int | None = None,
    execution_trace: dict | None = None,
) -> None:
    raw_deltas = {
        instrument: float(quantities.get(instrument, 0.0)) - position.get_stock_amount(instrument)
        for instrument in prices
    }
    current = {instrument: position.get_stock_amount(instrument) for instrument in prices}
    deltas = raw_deltas if request is None else _qlib_executable_deltas(
        request,
        int(row),
        strategy,
        quantities,
        current,
        float(position.position.get("cash", 0.0)),
    )
    if (
        request is not None
        and row is not None
        and execution_trace is not None
        and any(abs(delta) > 1e-12 for delta in deltas.values())
    ):
        execution_trace[timestamp.isoformat()] = execution_trace_entry(
            request,
            int(row),
            strategy,
            current,
            deltas,
            float(position.position.get("cash", 0.0)),
        )
    for direction in (Order.SELL, Order.BUY):
        for instrument, delta in deltas.items():
            if abs(delta) <= 1e-12 or (delta < 0) != (direction == Order.SELL):
                continue
            amount = abs(delta)
            order = Order(instrument, amount, direction, timestamp, timestamp, deal_amount=amount)
            fill_price = execution_price(prices[instrument], delta, strategy)
            trade_value = amount * fill_price
            position.update_order(
                order, trade_value, trade_value * fee_rate, fill_price
            )


def _qlib_executable_deltas(
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
