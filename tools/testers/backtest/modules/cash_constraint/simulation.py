"""Position-clone and cash-delta helpers for order-batch simulation."""

from __future__ import annotations

from collections import deque

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.modules.market_data import (
    contract_notional,
    historical_fields_for_product,
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
    fields = (
        product_fields
        if product_fields is not None
        else historical_fields_for_product(historical_fields, order.instrument)
    )
    if _uses_margin_accounting(
        strategy_config, historical_fields, order.instrument, ledger_config,
        product_fields=fields,
    ):
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
        )
        return float(after.to_major() - cash.to_major())
    return -(contract_notional(
        price, order.quantity, historical_fields, order.instrument,
        product_fields=fields,
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
