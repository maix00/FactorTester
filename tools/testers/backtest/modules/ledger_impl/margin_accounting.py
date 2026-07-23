"""Accounting for margin-traded position fills."""

from __future__ import annotations

from typing import Any

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.engines.native.position import ProductPosition
from tools.testers.backtest.modules.engine import engine_mode_for
from tools.testers.backtest.modules.market_data import (
    contract_multiplier_from_fields,
    historical_fields_for_product,
)
from tools.testers.backtest.modules.trading_rule import (
    _resolve_daily_mark_to_market_enabled_for_ledger,
    _resolve_method,
)

from .cost_basis import apply_lot_fill, same_direction, sign, weighted_average_cost
from .margin_ratios import entry_margin_major, resolved_margin_ratio_for_position_after_fill


def apply_margin_accounting_fill(
    cash: DataMoney, positions: dict, strategy_config, product, *,
    quantity: float, price: float, fee_cost: float,
    historical_fields: dict, ledger_config=None,
    state: Any | None = None, timestamp: Any | None = None,
) -> DataMoney:
    fields = historical_fields_for_product(historical_fields, product)
    multiplier = contract_multiplier_from_fields(
        historical_fields, product, state=state, timestamp=timestamp,
    )
    entry = positions.setdefault(product, ProductPosition(quantity=0.0, average_cost=0.0))
    before_margin = entry_margin_major(entry)
    prior_quantity = float(entry.quantity or 0.0)
    new_quantity = prior_quantity + quantity
    method = _resolve_method(
        strategy_config, product, fields,
        require_exact=engine_mode_for(strategy_config) == "exact",
        ledger_config=ledger_config,
    )
    from tools.testers.backtest.modules.fee import _resolve_fee_mode
    daily_mtm = _resolve_daily_mark_to_market_enabled_for_ledger(
        product, fields, ledger_config=ledger_config,
    )
    if method in ("FIFO", "LIFO", "HIFO"):
        realized = apply_lot_fill(
            entry, method, quantity, price, multiplier,
            is_today=True if daily_mtm and _resolve_fee_mode(
                strategy_config, ledger_config,
            ) in {"auto", "custom", "exact"} else None,
        )
        if abs(new_quantity) <= 1e-12:
            new_quantity = 0.0
    else:
        realized, new_cost, new_quantity = average_cost_fill(
            prior_quantity, float(entry.average_cost or price),
            quantity, price, multiplier,
        )
        entry.average_cost = new_cost
    entry.quantity = int(round(new_quantity)) if isinstance(entry.quantity, int) else new_quantity
    after_margin = (
        abs(new_quantity) * price * multiplier
        * resolved_margin_ratio_for_position_after_fill(
            strategy_config, fields, new_quantity, price, multiplier, ledger_config,
        )
    )
    entry.margin_reserved = DataMoney.from_major(
        after_margin, currency=cash.currency, use_minor_units=cash.use_minor_units,
    )
    cash_delta = realized - fee_cost - (after_margin - before_margin)
    return cash + DataMoney.from_major(
        cash_delta, currency=cash.currency, use_minor_units=cash.use_minor_units,
    )


def average_cost_fill(
    prior_quantity: float, prior_cost: float, quantity: float,
    price: float, multiplier: float,
) -> tuple[float, float, float]:
    new_quantity = prior_quantity + quantity
    if prior_quantity == 0 or same_direction(prior_quantity, quantity):
        return 0.0, weighted_average_cost(
            prior_quantity, prior_cost, quantity, price,
        ), new_quantity
    close_abs = min(abs(quantity), abs(prior_quantity))
    realized = close_abs * (price - prior_cost) * sign(prior_quantity) * multiplier
    if abs(new_quantity) <= 1e-12:
        return realized, 0.0, 0.0
    return realized, price if abs(quantity) > abs(prior_quantity) else prior_cost, new_quantity
