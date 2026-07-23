from __future__ import annotations

import pandas as pd

from tools.testers.backtest.engines.native.order import (
    Fill,
    Order,
    OrderAttempt,
    OrderOffset,
    OrderSide,
    OrderStatus,
)
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.order_lifecycle.schedule import (
    create_order_attempt,
)
from tools.testers.backtest.modules.order_lifecycle.store import OrderStore


def _order(order_id: str = "O1") -> Order:
    return Order(
        instrument="FAKE_PRODUCT",
        timestamp=pd.Timestamp("2024-01-01"),
        quantity=10.0,
        intent_quantity=10.0,
        strategy=Strategy(alias="S"),
        order_id=order_id,
    )


def test_store_keeps_one_order_across_multiple_fills():
    store = OrderStore()
    order = _order()
    store.register_order(order)

    for sequence, quantity in enumerate((3.0, 2.0), start=1):
        store.record_fill(Fill(
            fill_id=f"F{sequence}",
            order_id=order.order_id,
            attempt_id=f"A{sequence}",
            timestamp=pd.Timestamp("2024-01-01") + pd.Timedelta(minutes=sequence),
            quantity=quantity,
            price=100.0,
            side=OrderSide.BUY,
            offset=OrderOffset.OPEN,
        ))

    assert store.orders_by_id["O1"] is order
    assert [fill.quantity for fill in store.fills_by_order["O1"]] == [3.0, 2.0]
    assert order.status is OrderStatus.PARTIALLY_FILLED
    assert order.remaining_quantity == 5.0


def test_stale_attempt_revision_is_not_actionable():
    store = OrderStore()
    order = _order()
    store.register_order(order)
    attempt = OrderAttempt(
        attempt_id="A1",
        order_id=order.order_id,
        revision=order.revision,
        timestamp=pd.Timestamp("2024-01-02"),
        market_timestamp=pd.Timestamp("2024-01-02"),
        _order=order,
    )
    store.register_attempt(attempt)
    order.revision += 1

    assert not store.attempt_is_actionable(attempt)


def test_removing_live_order_uses_reverse_scope_index_not_all_scopes():
    class NoValuesScan(dict):
        def values(self):
            raise AssertionError("live-order removal scanned every scope")

    store = OrderStore()
    first, second = _order("O1"), _order("O2")
    store.register_order(first, scope="scope-1")
    store.register_order(second, scope="scope-2")
    store.live_order_ids_by_scope = NoValuesScan(
        store.live_order_ids_by_scope
    )

    store.remove_from_live_indexes(first)

    assert store.live_orders("scope-1") == ()
    assert store.live_orders("scope-2") == (second,)


def test_retries_keep_one_submit_request_lineage():
    state = BacktestRunState()
    order = _order()
    state.order_store.register_order(order)

    for minute in (1, 2):
        timestamp = pd.Timestamp("2024-01-01") + pd.Timedelta(minutes=minute)
        create_order_attempt(
            state, order,
            timestamp=timestamp, market_timestamp=timestamp,
        )

    actions = state.order_store.actions_by_order[order.order_id]
    assert [(action.action.value, action.request_id) for action in actions] == [
        ("submit", "O1:request:1"),
    ]
