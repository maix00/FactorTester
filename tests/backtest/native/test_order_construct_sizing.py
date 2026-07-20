from __future__ import annotations

import uuid

import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_construct import OrderConstructModule, _construct_orders, _round_to_lot_sizes


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def _account(strategy, policy="floor_to_lot", *, engine_mode="basic"):
    config = StrategyConfig(strategy=strategy, field_values={
        EngineModule.engine_mode: engine_mode,
        OrderConstructModule.quantity_rounding_policy: policy,
    })
    return BacktestRunState(strategy_configs={strategy: config})


def test_floor_to_lot_rounds_magnitude_down():
    s = Strategy(alias="S")
    p1, p2 = _product(), _product()
    account = _account(s, "floor_to_lot")

    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(OrderConstructModule.raw_deltas, s, {p1: 23.0, p2: -23.0})
    ctx.set(MarketDataModule.lot_sizes, {p1: 10.0, p2: 10.0})

    _round_to_lot_sizes(account, ctx)
    rounded = ctx.get_for(OrderConstructModule.sized_deltas, s)
    assert rounded[p1] == 20.0    # floor(23/10)*10, never rounds up past the target
    assert rounded[p2] == -20.0   # magnitude floored, sign preserved


def test_nearest_lot_rounds_to_closest():
    s = Strategy(alias="S")
    p1, p2 = _product(), _product()
    account = _account(s, "nearest_lot")

    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(OrderConstructModule.raw_deltas, s, {p1: 23.0, p2: 7.0})
    ctx.set(MarketDataModule.lot_sizes, {p1: 10.0, p2: 5.0})

    _round_to_lot_sizes(account, ctx)
    rounded = ctx.get_for(OrderConstructModule.sized_deltas, s)
    assert rounded[p1] == 20.0  # round(23/10)*10
    assert rounded[p2] == 5.0   # round(7/5)*5


def test_rounding_uses_existing_deltas_without_recomputing_size_order():
    s = Strategy(alias="S")
    p = _product()
    account = _account(s)

    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(OrderConstructModule.raw_deltas, s, {p: 23.0})
    ctx.set(MarketDataModule.lot_sizes, {p: 10.0})

    _round_to_lot_sizes(account, ctx)
    assert ctx.get_for(OrderConstructModule.sized_deltas, s)[p] == 20.0
    assert ctx.get_for(OrderConstructModule.deltas, s)[p] == 20.0


def test_construct_orders_consumes_rounded_deltas_after_sizing_pipeline():
    s = Strategy(alias="S")
    p = _product()
    account = _account(s)

    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(OrderConstructModule.raw_deltas, s, {p: 23.0})
    ctx.set(MarketDataModule.lot_sizes, {p: 10.0})

    _round_to_lot_sizes(account, ctx)
    _construct_orders(account, ctx)

    orders = ctx.get_for(OrderConstructModule.orders, s)
    assert len(orders) == 1
    assert orders[0].quantity == 20.0


def test_basic_missing_lot_size_defaults_to_no_rounding():
    s = Strategy(alias="S")
    p = _product()
    account = _account(s, engine_mode="basic")

    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(OrderConstructModule.raw_deltas, s, {p: 12.34})
    ctx.set(MarketDataModule.lot_sizes, {})

    _round_to_lot_sizes(account, ctx)
    assert ctx.get_for(OrderConstructModule.sized_deltas, s)[p] == pytest.approx(12.34)


def test_auto_missing_lot_size_defaults_to_one_lot_integer_rounding():
    s = Strategy(alias="S")
    p = _product()
    account = _account(s, engine_mode="auto")

    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(OrderConstructModule.raw_deltas, s, {p: 12.34, _product(): -0.4})
    ctx.set(MarketDataModule.lot_sizes, {})

    _round_to_lot_sizes(account, ctx)
    rounded = ctx.get_for(OrderConstructModule.sized_deltas, s)
    assert rounded[p] == 12.0
    assert sorted(rounded.values()) == [-0.0, 12.0]
