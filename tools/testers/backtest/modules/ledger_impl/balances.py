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

    config = state.config_for(strategy)
    if order is not None and callable(getattr(state, "ledger_for", None)):
        # ORDER replay already carries the authoritative routing decision and
        # BacktestRunState caches it by order identity.  Re-entering the
        # strategy/product route resolver here only repeats static policy and
        # ledger validation; it must remain the fallback for lightweight
        # callers that do not expose ``ledger_for``.
        ledger = state.ledger_for(order)
    else:
        ledger = ledger_for_strategy_product(
            state, strategy, product, timestamp=timestamp, order=order,
        )
    ledger_config = state.ledger_config_for(ledger)
    if not _resolve_use_int_position(config, ledger_config):
        return quantity
    lot_sizes = market_data_store_for(state).raw_input.get("lot_sizes") or {}
    policy = config.get(
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
    strategy_config,
    historical_fields: dict,
    product,
    ledger_config=None,
    *,
    product_fields: dict | None = None,
) -> bool:
    from tools.testers.backtest.modules.margin import product_uses_margin_accounting

    return product_uses_margin_accounting(
        (
            product_fields
            if product_fields is not None
            else historical_fields_for_product(historical_fields, product)
        ),
        ledger_config,
    )


def sync_ledger_margin_reserved(
    ledger, positions: dict, *, changed_product=None,
    previous_ledger_reserved: float | None = None,
    previous_product_reserved: float | None = None,
) -> None:
    from tools.testers.backtest.modules.margin import MarginModule

    if (
        changed_product is not None
        and previous_ledger_reserved is not None
        and previous_product_reserved is not None
        and ledger.get(MarginModule.margin_reserved, None) is not None
    ):
        # A fill changes the margin component of one product only.  The
        # ledger's reserved amount is already the sum from the preceding
        # ledger/margin flow, so update that aggregate instead of scanning
        # every open position after each fill.  Keep a full-scan fallback for
        # callers that do not provide the changed component or for an
        # uninitialised ledger.
        changed_entry = positions.get(changed_product)
        reserved = (
            float(previous_ledger_reserved)
            - float(previous_product_reserved)
            + (
                entry_margin_major(changed_entry)
                if changed_entry is not None else 0.0
            )
        )
    else:
        reserved = sum(entry_margin_major(entry) for entry in positions.values())
    if ledger.get(MarginModule.margin_requirement, None) is None and reserved <= 0:
        return
    ledger.set(MarginModule.margin_reserved, reserved)
    required = float(ledger.get(MarginModule.margin_requirement, reserved) or 0.0)
    deficit = float(ledger.get(MarginModule.margin_deficit, 0.0) or 0.0)
    ledger.set(MarginModule.margin_excess, max(reserved - required, 0.0))
    ledger.set(MarginModule.margin_deficit, 0.0 if reserved >= required else deficit)
