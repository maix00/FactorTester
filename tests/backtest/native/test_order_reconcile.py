from __future__ import annotations

import pandas as pd

from tools.testers.backtest.engines.native.order import Order, OrderGroup, OrderStatus
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.order_lifecycle import reconcile_target_delta


def _live_order(state, strategy, quantity=7.0):
    order = Order(
        instrument="P1",
        timestamp=pd.Timestamp("2024-01-01"),
        quantity=quantity,
        intent_quantity=quantity,
        strategy=strategy,
        order_id="O1",
        status=OrderStatus.PARTIALLY_FILLED,
        filled_quantity=3.0,
        requested_quantity=10.0,
        accepted_quantity=10.0,
        order_group_id="G1",
    )
    state.order_store.register_group(OrderGroup(
        order_group_id="G1",
        parent_intent_id="I1",
        created_at=pd.Timestamp("2024-01-01"),
        child_order_ids=("O1",),
    ))
    state.order_store.register_order(order)
    return order


def test_same_target_retains_live_remainder_without_new_delta():
    strategy = Strategy(alias="S")
    state = BacktestRunState()
    order = _live_order(state, strategy)

    delta = reconcile_target_delta(
        state,
        strategy,
        "P1",
        actual_quantity=3.0,
        target_quantity=10.0,
        timestamp=pd.Timestamp("2024-01-02"),
    )

    assert delta == 0.0
    assert order.status is OrderStatus.PARTIALLY_FILLED


def test_changed_target_cancels_remainder_and_rebuilds_from_actual():
    strategy = Strategy(alias="S")
    state = BacktestRunState()
    order = _live_order(state, strategy)

    delta = reconcile_target_delta(
        state,
        strategy,
        "P1",
        actual_quantity=3.0,
        target_quantity=8.0,
        timestamp=pd.Timestamp("2024-01-02"),
    )

    assert delta == 5.0
    assert order.status is OrderStatus.CANCELLED
    assert order.revision == 1
    assert state.order_store.superseded_group_id_by_scope[
        (strategy, "P1")
    ] == "G1"
