"""Position-clone and cash-delta helpers for order-batch simulation."""

from __future__ import annotations

from collections import deque
from typing import NamedTuple

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.modules.market_data import (
    contract_notional,
    contract_multiplier_from_product_fields,
    historical_fields_for_product,
)


class CashStaticInputs(NamedTuple):
    """Per-order values that are immutable for one cash-constraint batch.

    Cash simulation still receives the candidate order and mutable position
    snapshot on every call.  These fields, however, depend only on the
    current product row and ledger/strategy rules, so a reversing order can
    reuse them for its reducing and increasing legs without carrying state
    across timestamps.
    """

    product_fields: dict
    multiplier: float
    margin_accounting: bool
    method: str | None
    daily_mark_to_market: bool | None


def resolve_cash_static_inputs(
    strategy_config,
    product,
    historical_fields: dict,
    ledger_config,
    *,
    product_fields: dict | None = None,
    multiplier: float | None = None,
    state=None,
    timestamp=None,
) -> CashStaticInputs:
    """Resolve the immutable part of one order's cash simulation.

    The default call path in :func:`estimated_execution_cash_delta` remains
    unchanged when no inputs are supplied.  Constraint flows use this helper
    only for a local, per-batch cache; ``state``/``timestamp`` are optional so
    execution-stage resolution keeps the historical fallback-audit behavior.
    """
    from tools.testers.backtest.modules.engine import engine_mode_for
    from tools.testers.backtest.modules.ledger_module import (
        _resolve_method,
        _uses_margin_accounting,
    )
    from tools.testers.backtest.modules.trading_rule import (
        _resolve_daily_mark_to_market_enabled_for_ledger,
    )

    fields = (
        product_fields
        if product_fields is not None
        else historical_fields_for_product(historical_fields, product)
    )
    resolved_multiplier = multiplier
    if resolved_multiplier is None:
        resolved_multiplier = contract_multiplier_from_product_fields(
            fields, state=state, product=product, timestamp=timestamp,
        )
    margin_accounting = _uses_margin_accounting(
        strategy_config, historical_fields, product, ledger_config,
        product_fields=fields,
    )
    method = None
    daily_mark_to_market = None
    if margin_accounting:
        method = _resolve_method(
            strategy_config,
            product,
            fields,
            require_exact=engine_mode_for(strategy_config) == "exact",
            ledger_config=ledger_config,
        )
        daily_mark_to_market = _resolve_daily_mark_to_market_enabled_for_ledger(
            product, fields, ledger_config=ledger_config,
        )
    return CashStaticInputs(
        fields,
        float(resolved_multiplier),
        margin_accounting,
        method,
        daily_mark_to_market,
    )


def estimated_execution_cash_delta(
    cash: DataMoney,
    positions: dict,
    strategy_config,
    order,
    historical_fields: dict,
    ledger_config,
    current_prices: dict,
    *,
    product_fields: dict | None = None,
    static_inputs: CashStaticInputs | None = None,
) -> float:
    from tools.testers.backtest.modules.ledger_module import (
        _apply_margin_accounting_fill,
        _uses_margin_accounting,
    )

    effective_price = order.get("effective_price")
    price = float(
        effective_price
        if effective_price is not None
        else current_prices[order.instrument]
    )
    fee_cost = float(order.get("fee_cost", 0.0) or 0.0)
    static = static_inputs
    if static is None:
        fields = (
            product_fields
            if product_fields is not None
            else historical_fields_for_product(historical_fields, order.instrument)
        )
        margin_accounting = _uses_margin_accounting(
            strategy_config, historical_fields, order.instrument, ledger_config,
            product_fields=fields,
        )
    else:
        fields = static.product_fields
        margin_accounting = static.margin_accounting
    if margin_accounting:
        after = _apply_margin_accounting_fill(
            cash,
            positions,
            strategy_config,
            order.instrument,
            quantity=float(order.quantity),
            price=price,
            fee_cost=fee_cost,
            historical_fields=historical_fields,
            ledger_config=ledger_config,
            product_fields=fields,
            multiplier=None if static is None else static.multiplier,
            method=None if static is None else static.method,
            daily_mark_to_market=(
                None if static is None else static.daily_mark_to_market
            ),
        )
        return float(after.to_major() - cash.to_major())
    return -(contract_notional(
        price, order.quantity, historical_fields, order.instrument,
        product_fields=fields,
        multiplier=None if static is None else static.multiplier,
    ) + fee_cost)


def clone_positions(positions: dict) -> dict:
    from tools.testers.backtest.engines.native.position import Lot, ProductPosition

    cloned = {}
    for product, entry in positions.items():
        if isinstance(entry, ProductPosition):
            lots = entry.lots
            cloned[product] = ProductPosition(
                quantity=entry.quantity,
                average_cost=entry.average_cost,
                lots=deque(
                    Lot(
                        quantity=lot.quantity,
                        entry_price=lot.entry_price,
                        multiplier=lot.multiplier,
                        is_today=lot.is_today,
                    )
                    for lot in lots
                ) if lots is not None else None,
                margin_reserved=entry.margin_reserved,
                settlement_price=entry.settlement_price,
            )
            continue
        # Keep the compatibility path for lightweight test doubles that only
        # expose the ProductPosition attributes through getattr.
        lots = getattr(entry, "lots", None)
        cloned[product] = ProductPosition(
            quantity=getattr(entry, "quantity", 0.0),
            average_cost=getattr(entry, "average_cost", None),
            lots=deque(
                Lot(
                    quantity=lot.quantity,
                    entry_price=lot.entry_price,
                    multiplier=lot.multiplier,
                    is_today=lot.is_today,
                )
                for lot in lots
            ) if lots is not None else None,
            margin_reserved=getattr(entry, "margin_reserved", None),
            settlement_price=getattr(entry, "settlement_price", None),
        )
    return cloned
