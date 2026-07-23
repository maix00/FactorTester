"""Accounting for fully funded position fills."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.engines.native.position import ProductPosition
from tools.testers.backtest.engines.native.order import OrderOffset
from tools.testers.backtest.modules.engine import engine_mode_for
from tools.testers.backtest.modules.market_data import (
    contract_multiplier_from_fields,
    historical_fields_for_product,
)
from tools.testers.backtest.modules.trading_rule import _resolve_method

from .cost_basis import apply_lot_fill, same_direction, sign, weighted_average_cost


def apply_cash_accounting_position_fill(
    positions: dict, strategy_config, product, *,
    quantity: float, price: float, historical_fields: dict,
    ledger_config=None, state: Any | None = None, timestamp: Any | None = None,
    offset: OrderOffset = OrderOffset.AUTO,
) -> float:
    fields = historical_fields_for_product(historical_fields, product)
    multiplier = contract_multiplier_from_fields(
        historical_fields, product, state=state, timestamp=timestamp,
    )
    entry = positions.setdefault(product, ProductPosition(quantity=0.0, average_cost=0.0))
    prior_quantity = float(entry.quantity or 0.0)
    new_quantity = prior_quantity + quantity
    method = _resolve_method(
        strategy_config, product, fields,
        require_exact=engine_mode_for(strategy_config) == "exact",
        ledger_config=ledger_config,
    )
    realized = 0.0
    if method in ("FIFO", "LIFO", "HIFO"):
        realized = apply_lot_fill(
            entry, method, quantity, price, multiplier,
            is_today=None, offset=offset,
        )
        if abs(new_quantity) <= 1e-12:
            new_quantity = 0.0
    else:
        prior_cost = float(entry.average_cost or price)
        if prior_quantity == 0 or same_direction(prior_quantity, quantity):
            entry.average_cost = weighted_average_cost(
                prior_quantity, prior_cost, quantity, price,
            )
        else:
            close_abs = min(abs(quantity), abs(prior_quantity))
            realized = (
                close_abs * (price - prior_cost)
                * sign(prior_quantity) * multiplier
            )
            if abs(new_quantity) <= 1e-12:
                entry.average_cost = 0.0
                new_quantity = 0.0
            elif abs(quantity) > abs(prior_quantity):
                entry.average_cost = price
    entry.quantity = int(round(new_quantity)) if isinstance(entry.quantity, int) else new_quantity
    return realized
