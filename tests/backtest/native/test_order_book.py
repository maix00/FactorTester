from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.ledger import ProductPosition
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.group_membership import GroupMembershipModule
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_book import OrderBookModule, _basic_size_order, _construct_orders


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def test_basic_size_order_computes_deltas_from_target_weights():
    s = Strategy(alias="S")
    p1, p2 = _product(), _product()
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {p1: 10.0, p2: 20.0})
    ctx.set_for(LedgerModule.equity, s, 1000.0)
    ctx.set_for(GroupMembershipModule.target_weights, s, {p1: 0.5, p2: 0.5})

    class _FakeLedger:
        def get(self, ref, default=None):
            return {p1: ProductPosition(quantity=0.0), p2: ProductPosition(quantity=0.0)}

    class _FakeAccount:
        ledgers = {s: _FakeLedger()}

    _basic_size_order(_FakeAccount(), ctx)
    deltas = ctx.get_for(OrderBookModule.deltas, s)
    assert deltas[p1] == pytest.approx(50.0)   # 0.5*1000/10
    assert deltas[p2] == pytest.approx(25.0)   # 0.5*1000/20


def test_basic_size_order_uses_contract_multiplier_for_futures_notional():
    s = Strategy(alias="S")
    p = _product()
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set(MarketDataModule.current_historical_fields, {p: {"VolumeMultiple": 10.0}})
    ctx.set_for(LedgerModule.equity, s, 1000.0)
    ctx.set_for(GroupMembershipModule.target_weights, s, {p: 0.5})

    class _FakeLedger:
        def get(self, ref, default=None):
            return {p: ProductPosition(quantity=0.0)}

    class _FakeAccount:
        ledgers = {s: _FakeLedger()}

    _basic_size_order(_FakeAccount(), ctx)
    deltas = ctx.get_for(OrderBookModule.deltas, s)
    assert deltas[p] == pytest.approx(5.0)   # 0.5*1000/(10 price * 10 multiplier)


def test_basic_size_order_subtracts_existing_position():
    s = Strategy(alias="S")
    p1 = _product()
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {p1: 10.0})
    ctx.set_for(LedgerModule.equity, s, 1000.0)
    ctx.set_for(GroupMembershipModule.target_weights, s, {p1: 1.0})

    class _FakeLedger:
        def get(self, ref, default=None):
            return {p1: ProductPosition(quantity=30.0)}

    class _FakeAccount:
        ledgers = {s: _FakeLedger()}

    _basic_size_order(_FakeAccount(), ctx)
    deltas = ctx.get_for(OrderBookModule.deltas, s)
    assert deltas[p1] == pytest.approx(100.0 - 30.0)  # target 100, already hold 30


def test_construct_orders_skips_zero_deltas():
    s = Strategy(alias="S")
    p1, p2 = _product(), _product()
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}))
    ctx.set_for(OrderBookModule.deltas, s, {p1: 0.0, p2: 12.5})

    _construct_orders(None, ctx)
    orders = ctx.get_for(OrderBookModule.orders, s)
    assert len(orders) == 1
    assert orders[0].instrument is p2
    assert orders[0].quantity == orders[0].intent_quantity == 12.5
