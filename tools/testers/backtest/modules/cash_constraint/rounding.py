"""Whole-lot rounding helpers for constrained orders."""

from __future__ import annotations


def round_execution_scaled_quantity(state, strategy, order, quantity: float) -> float:
    from tools.testers.backtest.modules.market_data import market_data_store_for
    from tools.testers.backtest.modules.order_construct import (
        OrderConstructModule,
        default_round_order_quantity,
    )
    from tools.testers.backtest.modules.strategy_book import ledger_for_strategy_product
    from tools.testers.backtest.modules.trading_rule import _resolve_use_int_position

    lot_sizes = market_data_store_for(state).raw_input.get("lot_sizes") or {}
    policy = state.config_for(strategy).get(
        OrderConstructModule.quantity_rounding_policy, "floor_to_lot",
    )
    lot_size = lot_sizes.get(order.instrument)
    if not lot_size:
        ledger = ledger_for_strategy_product(state, strategy, order.instrument)
        if _resolve_use_int_position(state.config_for(strategy), state.ledger_config_for(ledger)):
            lot_size = 1.0
    return default_round_order_quantity(quantity, lot_size, policy)


def scale_linear_fee_fields(order, scale: float) -> None:
    for key in (
        "fee_cost",
        "fee_open_quantity",
        "fee_close_quantity",
        "fee_close_today_quantity",
        "fee_close_yesterday_quantity",
    ):
        value = order.get(key, None)
        if value is not None:
            order.set(key, float(value) * scale)
