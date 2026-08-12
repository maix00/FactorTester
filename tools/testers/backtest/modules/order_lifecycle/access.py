"""State accessors for run-scoped order lifecycle stores."""

from __future__ import annotations

from typing import Any

from .audit_store import OrderFlowStore
from .store import OrderStore


def order_stores_for(state: Any) -> tuple[OrderStore, OrderFlowStore]:
    """Return lifecycle stores, attaching them to lightweight host states."""
    order_store = getattr(state, "order_store", None)
    if order_store is None:
        order_store = OrderStore()
        state.order_store = order_store
    audit_store = getattr(state, "order_flow_store", None)
    if audit_store is None:
        audit_store = OrderFlowStore()
        state.order_flow_store = audit_store
    return order_store, audit_store
