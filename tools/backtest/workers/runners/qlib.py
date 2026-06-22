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
    execution_price,
    parse_group_strategy_input,
    parse_target_weight_input,
    rebalance_mode,
    target_quantities,
    target_rows,
    valuation_price,
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
        mode = rebalance_mode(strategy)
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
            "positions": position.get_stock_amount_dict(),
            "equity_curve": equity_curve,
            "position_curve": position_curve,
        }
    return {"engine": "qlib", "portfolios": portfolios}


def run_group_strategy(payload: Mapping[str, Any], progress=None) -> dict[str, Any]:
    request, memberships, updates, calculators = parse_group_strategy_input(payload)
    portfolios = {}
    for strategy_position, (strategy, calculator) in enumerate(
        zip(request.strategies, calculators, strict=True)
    ):
        strategy_cash = float(strategy.get("initial_capital") or request.initial_cash)
        position = _SignedPosition(cash=strategy_cash)
        pending = None
        equity_curve = {}
        position_curve = {}
        for row, timestamp in enumerate(request.timestamps):
            current_prices = {
                instrument: valuation_price(request, row, instrument)
                for instrument in request.instruments
            }
            for instrument in position.get_stock_list():
                position.update_stock_price(instrument, current_prices[instrument])
            if pending is not None:
                _rebalance(
                    position,
                    target_quantities(
                        request, row, pending, float(position.calculate_value()), strategy
                    ),
                    current_prices,
                    timestamp,
                    fee_rate=float(strategy.get("fee_rate") or 0.0),
                    strategy=strategy,
                    request=request,
                    row=row,
                )
            equity_curve[timestamp.isoformat()] = float(position.calculate_value())
            position_curve[timestamp.isoformat()] = {
                instrument: float(position.get_stock_amount(instrument))
                for instrument in request.instruments
            }
            pending = calculator.update(
                timestamp,
                np.asarray([request.prices[name][row] for name in request.instruments]),
                memberships[row],
                updates[row],
                np.asarray(request.margin_ratios[row]),
            )
            if progress is not None and strategy_position == 0:
                progress(row + 1, len(request.timestamps), timestamp)
        portfolios[calculator.strategy_id] = {
            "initial_value": strategy_cash,
            "final_value": float(position.calculate_value()),
            "positions": position.get_stock_amount_dict(),
            "equity_curve": equity_curve,
            "position_curve": position_curve,
        }
    return {
        "engine": "qlib",
        "portfolios": portfolios,
        "target_trace": {item.strategy_id: item.target_trace for item in calculators},
        "strategy_diagnostics": {
            item.strategy_id: {**item.diagnostics, **market_rule_diagnostics(payload)}
            for item in calculators
        },
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
) -> None:
    raw_deltas = {
        instrument: float(quantities.get(instrument, 0.0)) - position.get_stock_amount(instrument)
        for instrument in prices
    }
    deltas = raw_deltas if request is None else capacity_limited_deltas(
        request,
        int(row),
        strategy,
        quantities,
        {instrument: position.get_stock_amount(instrument) for instrument in prices},
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
