from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.position import ProductPosition
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.group_membership import GroupMembershipModule
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_construct import OrderConstructModule, _basic_size_order, _construct_orders
from tools.testers.backtest.modules.strategy_book import StrategyBookPolicies, strategy_book_store_for
from tools.testers.backtest.modules.target import OrderDeltaIntent, TargetStrategyModule
from tools.traderules import OrderTradeConstraint


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
        def ledger_for_strategy(self, strategy):
            return self.ledgers[strategy]

    _basic_size_order(_FakeAccount(), ctx)
    deltas = ctx.get_for(OrderConstructModule.raw_deltas, s)
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
        def ledger_for_strategy(self, strategy):
            return self.ledgers[strategy]

    _basic_size_order(_FakeAccount(), ctx)
    deltas = ctx.get_for(OrderConstructModule.raw_deltas, s)
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
        def ledger_for_strategy(self, strategy):
            return self.ledgers[strategy]

    _basic_size_order(_FakeAccount(), ctx)
    deltas = ctx.get_for(OrderConstructModule.raw_deltas, s)
    assert deltas[p1] == pytest.approx(100.0 - 30.0)  # target 100, already hold 30


def test_order_delta_intent_bypasses_target_weight_equity_sizing():
    s = Strategy(alias="S")
    p = _product()
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}))
    ctx.set_for(TargetStrategyModule.trade_intent, s, OrderDeltaIntent({p: 3.0}, reason="technical_rule"))

    class _FakeAccount:
        pass

    _basic_size_order(_FakeAccount(), ctx)

    assert ctx.get_for(OrderConstructModule.raw_deltas, s) == {p: 3.0}


def test_strategy_book_order_sizing_policy_can_override_default_deltas():
    s = Strategy(alias="S")
    p = _product()
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set_for(LedgerModule.equity, s, 1000.0)
    ctx.set_for(GroupMembershipModule.target_weights, s, {p: 1.0})

    class _FakeLedger:
        def get(self, ref, default=None):
            return {p: ProductPosition(quantity=0.0)}

    class _FakeAccount:
        ledgers = {s: _FakeLedger()}
        def ledger_for_strategy(self, strategy):
            return self.ledgers[strategy]

    account = _FakeAccount()
    strategy_book_store_for(account).policies = StrategyBookPolicies(
        order_sizing=lambda _state, _ctx, _strategy, deltas: {
            product: quantity * 0.5 for product, quantity in deltas.items()
        }
    )

    _basic_size_order(account, ctx)

    assert ctx.get_for(OrderConstructModule.raw_deltas, s)[p] == pytest.approx(50.0)


def test_basic_size_order_keeps_untradable_position_and_records_runtime_info():
    s = Strategy(alias="S")
    p = _product()
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01 09:01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {})
    ctx.set(MarketDataModule.current_tradable_status, {p: False})
    ctx.set_for(LedgerModule.equity, s, 1000.0)
    # Target dropped to zero, but the product cannot trade at this timestamp.
    # The engine must keep the position instead of crashing on prices[p] or
    # generating an impossible sell order.
    ctx.set_for(GroupMembershipModule.target_weights, s, {})

    class _FakeLedger:
        def get(self, ref, default=None):
            return {p: ProductPosition(quantity=30.0)}

    class _FakeAccount:
        ledgers = {s: _FakeLedger()}
        def ledger_for_strategy(self, strategy):
            return self.ledgers[strategy]
        runtime_info_rows = []
        runtime_info_sink = None

    account = _FakeAccount()
    _basic_size_order(account, ctx)

    assert ctx.get_for(OrderConstructModule.raw_deltas, s) == {}
    assert account.runtime_info_rows
    assert account.runtime_info_rows[0]["code"] == "order_target_skipped_untradable"


def test_basic_size_order_uses_coarse_tradability_not_side_constraints_for_closeout():
    s = Strategy(alias="S")
    p = _product()
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01 09:01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set(MarketDataModule.current_tradable_status, {p: True})
    ctx.set(MarketDataModule.current_order_constraints, {
        p: OrderTradeConstraint(
            tradable=True,
            can_buy=False,
            can_sell=True,
            reason="触及涨停，买入方向不可成交",
        )
    })
    ctx.set_for(LedgerModule.equity, s, 1000.0)
    # Target dropped to zero. Even if the bar is upper-limit locked, sizing
    # must still produce the sell delta; side-specific constraints are applied
    # later by OrderExecutionModule once the order direction is known.
    ctx.set_for(GroupMembershipModule.target_weights, s, {})

    class _FakeLedger:
        def get(self, ref, default=None):
            return {p: ProductPosition(quantity=30.0)}

    class _FakeAccount:
        ledgers = {s: _FakeLedger()}
        def ledger_for_strategy(self, strategy):
            return self.ledgers[strategy]

    _basic_size_order(_FakeAccount(), ctx)

    assert ctx.get_for(OrderConstructModule.raw_deltas, s) == {p: -30.0}


def test_construct_orders_skips_zero_deltas():
    s = Strategy(alias="S")
    p1, p2 = _product(), _product()
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}))
    ctx.set_for(OrderConstructModule.deltas, s, {p1: 0.0, p2: 12.5})

    account = BacktestRunState()
    _construct_orders(account, ctx)
    orders = ctx.get_for(OrderConstructModule.orders, s)
    assert len(orders) == 1
    assert orders[0].instrument is p2
    assert orders[0].quantity == orders[0].intent_quantity == 12.5
    assert orders[0].order_id
    assert account.order_flow_store.records_for_order(orders[0].order_id)[0]["step"] == "construct_order"
