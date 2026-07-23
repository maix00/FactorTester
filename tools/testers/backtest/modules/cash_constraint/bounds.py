"""Cheap conservative cash-requirement bound before exact simulation."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    contract_multiplier_from_fields,
    contract_notional,
    historical_fields_for_product,
)

from .pnl import realized_pnl_estimate


def execution_cash_required_upper_bound(
    state,
    ctx,
    ledger,
    entries: list[tuple[Any, list[Any], dict]],
) -> float:
    prices = ctx.get(MarketDataModule.current_prices, {})
    positions = ledger.get(LedgerModule.positions, {})
    total = 0.0
    for strategy, orders, historical_fields in entries:
        config = state.config_for(strategy)
        ledger_config = state.ledger_config_for(ledger)
        for order in orders:
            price = float(order.get("effective_price", prices[order.instrument]))
            fee = max(float(order.get("fee_cost", 0.0) or 0.0), 0.0)
            if _uses_margin(config, historical_fields, order.instrument, ledger_config):
                total += fee + _margin_increase(
                    config, positions, order, price, historical_fields, ledger_config,
                )
                total += max(-realized_pnl_estimate(
                    config, positions, order, price, historical_fields, ledger_config,
                ), 0.0)
            else:
                notional = contract_notional(
                    price, order.quantity, historical_fields, order.instrument,
                )
                total += max(notional + fee, 0.0)
    return total


def _uses_margin(config, historical_fields, product, ledger_config) -> bool:
    from tools.testers.backtest.modules.ledger_module import _uses_margin_accounting

    return _uses_margin_accounting(config, historical_fields, product, ledger_config)


def _margin_increase(config, positions, order, price, historical, ledger_config) -> float:
    from tools.testers.backtest.modules.ledger_module import (
        _entry_margin_major,
        _resolved_margin_ratio_for_position_after_fill,
    )

    entry = positions.get(order.instrument)
    prior = float(getattr(entry, "quantity", 0.0) or 0.0)
    new_quantity = prior + float(order.quantity)
    before = _entry_margin_major(entry) if entry is not None else 0.0
    multiplier = contract_multiplier_from_fields(historical, order.instrument)
    ratio = _resolved_margin_ratio_for_position_after_fill(
        config,
        historical_fields_for_product(historical, order.instrument),
        new_quantity,
        price,
        multiplier,
        ledger_config,
    )
    after = abs(new_quantity) * price * multiplier * ratio
    return max(after - before, 0.0)
