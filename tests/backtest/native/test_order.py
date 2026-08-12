from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from tools.testers.backtest.engines.native.order import (
    Fill,
    Order,
    OrderOffset,
    OrderSide,
    OrderStatus,
)
from tools.testers.backtest.engines.native.strategy import Strategy


def test_order_get_set_roundtrip():
    order = Order(
        instrument="FAKE_PRODUCT",  # plain placeholder ok for this unit test
        timestamp=pd.Timestamp("2024-01-01"),
        quantity=10.0,
        intent_quantity=10.0,
        strategy=Strategy(alias="S1"),
    )
    assert order.get("missing", "default") == "default"
    order.set("foo", 42)
    assert order.get("foo") == 42


def test_order_keeps_legacy_constructor_fields_and_adds_lifecycle_fields():
    names = {f.name for f in dataclasses.fields(Order)}
    assert {
        "instrument", "timestamp", "quantity", "intent_quantity",
        "strategy", "status", "reject_reason", "order_id", "fields",
    } <= names
    assert {
        "requested_quantity", "filled_quantity", "order_group_id",
        "parent_intent_id", "leg_role", "offset", "revision",
    } <= names


def test_order_default_status_is_draft():
    order = Order(
        instrument="FAKE_PRODUCT",
        timestamp=pd.Timestamp("2024-01-01"),
        quantity=1.0,
        intent_quantity=1.0,
        strategy=Strategy(alias="S2"),
    )
    assert order.status == OrderStatus.DRAFT


def test_partial_fill_keeps_one_order_and_quantity_invariant():
    order = Order(
        instrument="FAKE_PRODUCT",
        timestamp=pd.Timestamp("2024-01-01"),
        quantity=-10.0,
        intent_quantity=-10.0,
        strategy=Strategy(alias="S3"),
    )

    order.register_fill(3.0)

    assert order.side is OrderSide.SELL
    assert order.status is OrderStatus.PARTIALLY_FILLED
    assert order.filled_quantity == 3.0
    assert order.remaining_quantity == 7.0
    assert order.signed_remaining_quantity == -7.0
    assert order.filled_quantity + order.remaining_quantity == order.current_order_quantity


def test_terminal_order_preserves_unfilled_audit_quantity():
    order = Order(
        instrument="FAKE_PRODUCT",
        timestamp=pd.Timestamp("2024-01-01"),
        quantity=10.0,
        intent_quantity=10.0,
        strategy=Strategy(alias="S4"),
    )
    order.register_fill(3.0)
    order.status = OrderStatus.CANCELLED

    assert order.remaining_quantity == 0.0
    assert order.unfilled_quantity == 7.0


def test_fill_is_positive_and_projects_signed_quantity():
    fill = Fill(
        fill_id="F1",
        order_id="O1",
        attempt_id="A1",
        timestamp=pd.Timestamp("2024-01-01"),
        quantity=2.0,
        price=100.0,
        side=OrderSide.SELL,
        offset=OrderOffset.CLOSE,
    )

    assert fill.signed_quantity == -2.0
    with pytest.raises(ValueError, match="positive"):
        dataclasses.replace(fill, quantity=0.0)
