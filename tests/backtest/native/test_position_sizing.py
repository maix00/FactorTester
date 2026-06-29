from __future__ import annotations

import uuid

import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.ledger import AccountState, StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_book import OrderBookModule
from tools.testers.backtest.modules.position_sizing import PositionSizingModule, _round_to_lot_sizes


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def _account(strategy, policy="floor_to_lot"):
    config = StrategyConfig(strategy=strategy, field_values={
        PositionSizingModule.quantity_rounding_policy: policy,
    })
    return AccountState(strategy_configs={strategy: config})


def test_floor_to_lot_rounds_magnitude_down():
    s = Strategy(alias="S")
    p1, p2 = _product(), _product()
    account = _account(s, "floor_to_lot")

    def base_compute(account, ctx) -> None:
        ctx.set_for(OrderBookModule.deltas, s, {p1: 23.0, p2: -23.0})

    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.lot_sizes, {p1: 10.0, p2: 10.0})

    _round_to_lot_sizes(account, ctx, base_compute)
    rounded = ctx.get_for(OrderBookModule.deltas, s)
    assert rounded[p1] == 20.0    # floor(23/10)*10, never rounds up past the target
    assert rounded[p2] == -20.0   # magnitude floored, sign preserved


def test_nearest_lot_rounds_to_closest():
    s = Strategy(alias="S")
    p1, p2 = _product(), _product()
    account = _account(s, "nearest_lot")

    def base_compute(account, ctx) -> None:
        ctx.set_for(OrderBookModule.deltas, s, {p1: 23.0, p2: 7.0})

    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.lot_sizes, {p1: 10.0, p2: 5.0})

    _round_to_lot_sizes(account, ctx, base_compute)
    rounded = ctx.get_for(OrderBookModule.deltas, s)
    assert rounded[p1] == 20.0  # round(23/10)*10
    assert rounded[p2] == 5.0   # round(7/5)*5


def test_base_compute_runs_before_rounding():
    s = Strategy(alias="S")
    p = _product()
    account = _account(s)
    calls = []

    def base_compute(account, ctx) -> None:
        calls.append("base")
        ctx.set_for(OrderBookModule.deltas, s, {p: 23.0})

    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.lot_sizes, {p: 10.0})

    _round_to_lot_sizes(account, ctx, base_compute)
    assert calls == ["base"]


def test_missing_lot_size_defaults_to_no_rounding():
    s = Strategy(alias="S")
    p = _product()
    account = _account(s)

    def base_compute(account, ctx) -> None:
        ctx.set_for(OrderBookModule.deltas, s, {p: 12.34})

    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.lot_sizes, {})

    _round_to_lot_sizes(account, ctx, base_compute)
    assert ctx.get_for(OrderBookModule.deltas, s)[p] == pytest.approx(12.34)
