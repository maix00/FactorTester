"""Ledger balance and fill-quantity helpers."""

from __future__ import annotations

from tools.testers.backtest.modules.cash_pool import cash_for_ledger
from tools.testers.backtest.modules.market_data import historical_fields_for_product
from tools.testers.backtest.modules.trading_rule import _resolve_use_int_position

from .margin_ratios import entry_margin_major


def margin_reserved_major(ledger) -> float:
    from tools.testers.backtest.modules.margin import MarginModule

    return float(ledger.get(MarginModule.margin_reserved, 0.0) or 0.0)


def normalise_fill_quantity(
    state, strategy, product, quantity: float, *, order=None, timestamp=None,
) -> float:
    from tools.testers.backtest.modules.market_data import market_data_store_for
    from tools.testers.backtest.modules.order_construct import (
        OrderConstructModule,
        default_round_order_quantity,
    )
    from tools.testers.backtest.modules.strategy_book import ledger_for_strategy_product

    ledger = ledger_for_strategy_product(
        state, strategy, product, timestamp=timestamp, order=order,
    )
    if not _resolve_use_int_position(
        state.config_for(strategy), state.ledger_config_for(ledger),
    ):
        return quantity
    lot_sizes = market_data_store_for(state).raw_input.get("lot_sizes") or {}
    policy = state.config_for(strategy).get(
        OrderConstructModule.quantity_rounding_policy, "floor_to_lot",
    )
    return default_round_order_quantity(
        quantity, lot_sizes.get(product) or 1.0, policy,
    )


def required_cash_for_ledger(state, ledger):
    cash = cash_for_ledger(state, ledger)
    if cash is None:
        raise RuntimeError(f"ledger {getattr(ledger, 'ledger_id', ledger)!r} has no cash pool")
    return cash


def uses_margin_accounting(
    strategy_config, historical_fields: dict, product, ledger_config=None,
) -> bool:
    from tools.testers.backtest.modules.margin import product_uses_margin_accounting

    return product_uses_margin_accounting(
        historical_fields_for_product(historical_fields, product), ledger_config,
    )


def sync_ledger_margin_reserved(ledger, positions: dict) -> None:
    from tools.testers.backtest.modules.margin import MarginModule

    reserved = sum(entry_margin_major(entry) for entry in positions.values())
    if ledger.get(MarginModule.margin_requirement, None) is None and reserved <= 0:
        return
    ledger.set(MarginModule.margin_reserved, reserved)
    required = float(ledger.get(MarginModule.margin_requirement, reserved) or 0.0)
    deficit = float(ledger.get(MarginModule.margin_deficit, 0.0) or 0.0)
    ledger.set(MarginModule.margin_excess, max(reserved - required, 0.0))
    ledger.set(MarginModule.margin_deficit, 0.0 if reserved >= required else deficit)
