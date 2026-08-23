"""Persist immutable fill and ledger-settlement records."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.engines.native.order import Fill, FillSettlement


def record_fill_settlement(
    state: Any,
    order: Any,
    *,
    timestamp: Any,
    price: float,
    fee: float,
    realized_pnl: float,
    cash_before: float,
    cash_after: float,
    margin_before: float,
    margin_after: float,
    account_id: str = "",
    cash_pool_id: str = "",
    account_currency: str = "",
    cash_pool_base_currency: str = "",
) -> Fill:
    order_store = state.order_store
    audit_store = state.order_flow_store
    if not order.order_id:
        order.order_id = audit_store.next_order_id(order.strategy, order.timestamp)
    if order.order_id not in order_store.orders_by_id:
        order_store.register_order(order)
    sequence = len(order_store.fills_by_order.get(order.order_id, ())) + 1
    fill = Fill(
        fill_id=f"{order.order_id}:fill:{sequence}",
        order_id=order.order_id,
        attempt_id=str(order.get("active_attempt_id", "")),
        timestamp=timestamp,
        quantity=abs(float(order.quantity)),
        price=price,
        side=order.side,
        offset=order.offset,
        fee=fee,
    )
    order_store.record_fill(fill)
    order_store.record_settlement(FillSettlement(
        fill_id=fill.fill_id,
        realized_pnl=float(realized_pnl),
        fee=fee,
        cash_before=cash_before,
        cash_after=cash_after,
        margin_before=margin_before,
        margin_after=margin_after,
        account_id=account_id,
        cash_pool_id=cash_pool_id,
        account_currency=account_currency,
        cash_pool_base_currency=cash_pool_base_currency,
    ))
    return fill
