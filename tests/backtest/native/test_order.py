from __future__ import annotations

import dataclasses

import pandas as pd

from tools.testers.backtest.engines.native.order import Order, OrderStatus
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


def test_order_has_no_extra_named_fields():
    names = {f.name for f in dataclasses.fields(Order)}
    assert names == {
        "instrument", "timestamp", "quantity", "intent_quantity",
        "strategy", "status", "reject_reason", "fields",
    }


def test_order_default_status_is_draft():
    order = Order(
        instrument="FAKE_PRODUCT",
        timestamp=pd.Timestamp("2024-01-01"),
        quantity=1.0,
        intent_quantity=1.0,
        strategy=Strategy(alias="S2"),
    )
    assert order.status == OrderStatus.DRAFT
