"""Zipline target-weight runner using its Ledger transaction lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from zipline.assets import Equity
from zipline.assets.exchange_info import ExchangeInfo
from zipline.finance.ledger import Ledger
from zipline.finance.transaction import Transaction

from .common import parse_target_weight_input, rebalance_mode, target_rows


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
        ledger = Ledger(request.timestamps, request.initial_cash, "daily")
        targets = target_rows(strategy, request.timestamps)
        mode = rebalance_mode(strategy)
        pending = None
        transaction_number = 0
        for index, timestamp in enumerate(request.timestamps):
            current_prices = {
                instrument: request.prices[instrument][index]
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
                deltas = {
                    instrument: value * float(pending.get(instrument, 0.0)) / current_prices[instrument]
                    - ledger.position_tracker.positions[asset].amount
                    for instrument, asset in assets.items()
                }
                for sell_first in (True, False):
                    for instrument, delta in deltas.items():
                        if abs(delta) <= 1e-12 or (delta < 0) != sell_first:
                            continue
                        transaction_number += 1
                        ledger.process_transaction(Transaction(
                            assets[instrument],
                            delta,
                            timestamp,
                            current_prices[instrument],
                            f"order-{transaction_number}",
                        ))
            next_target = targets.get(timestamp)
            pending = next_target if next_target is not None else (
                pending if mode == "each_period" else None
            )
        portfolio = ledger.portfolio
        portfolios[strategy["strategy_id"]] = {
            "initial_value": request.initial_cash,
            "final_value": float(portfolio.portfolio_value),
            "positions": {
                instrument: float(
                    ledger.position_tracker.positions[asset].amount
                    if asset in ledger.position_tracker.positions else 0.0
                )
                for instrument, asset in assets.items()
            },
        }
    return {"engine": "zipline", "portfolios": portfolios}
