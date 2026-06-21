"""Qlib target-weight runner using Qlib's Position and Order lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from qlib.backtest.decision import Order
from qlib.backtest.position import Position

from .common import parse_target_weight_input, rebalance_mode, target_rows


def run_target_weights(payload: Mapping[str, Any]) -> dict[str, Any]:
    request = parse_target_weight_input(payload)
    portfolios = {}
    for strategy in request.strategies:
        position = Position(cash=request.initial_cash)
        targets = target_rows(strategy, request.timestamps)
        mode = rebalance_mode(strategy)
        pending = None
        for index, timestamp in enumerate(request.timestamps):
            current_prices = {
                instrument: request.prices[instrument][index]
                for instrument in request.instruments
            }
            for instrument in position.get_stock_list():
                position.update_stock_price(instrument, current_prices[instrument])
            if pending is not None:
                _rebalance(position, pending, current_prices, timestamp)
            next_target = targets.get(timestamp)
            pending = next_target if next_target is not None else (
                pending if mode == "each_period" else None
            )
        portfolios[strategy["strategy_id"]] = {
            "initial_value": request.initial_cash,
            "final_value": float(position.calculate_value()),
            "positions": position.get_stock_amount_dict(),
        }
    return {"engine": "qlib", "portfolios": portfolios}


def _rebalance(
    position: Position,
    weights: Mapping[str, float],
    prices: Mapping[str, float],
    timestamp,
) -> None:
    value = position.calculate_value()
    deltas = {
        instrument: value * float(weights.get(instrument, 0.0)) / prices[instrument]
        - position.get_stock_amount(instrument)
        for instrument in prices
    }
    for direction in (Order.SELL, Order.BUY):
        for instrument, delta in deltas.items():
            if abs(delta) <= 1e-12 or (delta < 0) != (direction == Order.SELL):
                continue
            amount = abs(delta)
            order = Order(instrument, amount, direction, timestamp, timestamp, deal_amount=amount)
            position.update_order(order, amount * prices[instrument], 0.0, prices[instrument])
