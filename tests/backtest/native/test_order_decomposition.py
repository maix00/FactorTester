from __future__ import annotations

from collections import deque

import pandas as pd
import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.order import (
    OrderLegRole,
    OrderOffset,
    OrderStatus,
)
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.position import Lot, ProductPosition
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.order_construction.decomposition import (
    decompose_position_delta,
)
from tools.testers.backtest.modules.order_lifecycle import activate_ready_dependents
from tools.testers.backtest.modules.ledger_impl.cost_basis import apply_lot_fill


def _product() -> Product:
    return Product(name="DECOMPOSE", point_value=1, currency="CNY")


def test_reversal_is_close_then_blocked_open_orders():
    strategy = Strategy(alias="reversal")
    group, orders = decompose_position_delta(
        strategy=strategy,
        product=_product(),
        timestamp=pd.Timestamp("2024-01-01 09:00"),
        delta=-15.0,
        position=ProductPosition(quantity=10.0),
        group_id="G1",
        parent_intent_id="I1",
        order_ids=iter(("C1", "O1")),
        cost_basis_method="FIFO",
    )

    assert [order.quantity for order in orders] == [-10.0, -5.0]
    assert [order.offset for order in orders] == [OrderOffset.CLOSE, OrderOffset.OPEN]
    assert orders[0].status == OrderStatus.DRAFT
    assert orders[1].status == OrderStatus.BLOCKED
    assert orders[1].get("depends_on_order_ids") == ("C1",)
    assert group.child_order_ids == ("C1", "O1")
    assert {order.order_group_id for order in orders} == {"G1"}


def test_dmtm_lots_become_explicit_close_yesterday_and_close_today_orders():
    strategy = Strategy(alias="dmtm")
    position = ProductPosition(
        quantity=3.0,
        lots=deque([
            Lot(quantity=1.0, entry_price=8.0, multiplier=1.0, is_today=False),
            Lot(quantity=2.0, entry_price=9.0, multiplier=1.0, is_today=True),
        ]),
    )
    group, orders = decompose_position_delta(
        strategy=strategy,
        product=_product(),
        timestamp=pd.Timestamp("2024-01-01 14:00"),
        delta=-5.0,
        position=position,
        group_id="G2",
        parent_intent_id="I2",
        order_ids=iter(("CY", "CT", "OPEN")),
        cost_basis_method="FIFO",
        require_exact_offsets=True,
    )

    assert [order.offset for order in orders] == [
        OrderOffset.CLOSE_YESTERDAY,
        OrderOffset.CLOSE_TODAY,
        OrderOffset.OPEN,
    ]
    assert [order.leg_role for order in orders] == [
        OrderLegRole.CLOSE_YESTERDAY,
        OrderLegRole.CLOSE_TODAY,
        OrderLegRole.OPEN,
    ]
    assert [order.quantity for order in orders] == [-1.0, -2.0, -2.0]
    assert orders[-1].get("depends_on_order_ids") == ("CY", "CT")
    assert group.execution_policy == "sequential_close_then_open"


@pytest.mark.parametrize(
    "position, message",
    [
        (ProductPosition(quantity=2.0), "complete position lots"),
        (
            ProductPosition(
                quantity=2.0,
                lots=deque([
                    Lot(
                        quantity=2.0, entry_price=8.0,
                        multiplier=1.0, is_today=None,
                    ),
                ]),
            ),
            "today/yesterday age",
        ),
    ],
)
def test_exact_reversal_rejects_missing_offset_facts_before_construction(
    position, message,
):
    with pytest.raises(ValueError, match=message):
        decompose_position_delta(
            strategy=Strategy(alias="exact"),
            product=_product(),
            timestamp=pd.Timestamp("2024-01-01 14:00"),
            delta=-2.0,
            position=position,
            group_id="G-exact",
            parent_intent_id="I-exact",
            order_ids=iter(("CLOSE",)),
            cost_basis_method="FIFO",
            require_exact_offsets=True,
        )


def test_blocked_open_activates_at_close_fill_timestamp():
    strategy = Strategy(alias="activate")
    timestamp = pd.Timestamp("2024-01-01 09:01")
    group, orders = decompose_position_delta(
        strategy=strategy,
        product=_product(),
        timestamp=timestamp,
        delta=-15.0,
        position=ProductPosition(quantity=10.0),
        group_id="G3",
        parent_intent_id="I3",
        order_ids=iter(("CLOSE", "OPEN")),
        cost_basis_method="FIFO",
    )
    close, opening = orders
    state = BacktestRunState()
    state.order_store.register_group(group)
    for order in orders:
        state.order_store.register_order(order)
    close.status = OrderStatus.FILLED
    close.set("active_market_timestamp", timestamp)
    ctx = FlowContext(
        timestamp=timestamp,
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
        drafts_by_strategy={
            strategy: [EventDraft(EventKind.ORDER, timestamp, strategy, close)],
        },
    )

    drafts = activate_ready_dependents(state, ctx)

    assert len(drafts) == 1
    assert drafts[0].timestamp == timestamp
    assert drafts[0].payload.order_id == opening.order_id
    assert opening.status == OrderStatus.SCHEDULED


def test_close_today_consumes_only_today_lots():
    position = ProductPosition(
        quantity=3.0,
        lots=deque([
            Lot(quantity=1.0, entry_price=8.0, multiplier=1.0, is_today=False),
            Lot(quantity=2.0, entry_price=9.0, multiplier=1.0, is_today=True),
        ]),
    )

    realized = apply_lot_fill(
        position, "FIFO", -1.0, 10.0, 1.0,
        offset=OrderOffset.CLOSE_TODAY,
    )

    assert realized == 1.0
    assert [(lot.quantity, lot.is_today) for lot in position.lots] == [
        (1.0, False),
        (1.0, True),
    ]
