from __future__ import annotations

import pandas as pd

from tools.products.Product import Product
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.order import Order, OrderOffset
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.execution_capacity.matching import allocate_order_capacity
from tools.testers.backtest.modules.cash_pool import set_cash_for_ledger_pool
from tools.testers.backtest.modules.ledger_module import _apply_order_fill
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_lifecycle import (
    create_order_attempt,
    finalize_and_retry_orders,
)
from tools.testers.backtest.modules.order_execution import OrderExecutionModule
from tools.testers.backtest.modules.volume_capacity import VolumeCapacityMode
from tools.data.types.data_money import DataMoney


def _product() -> Product:
    return Product(name="CAPACITY-TEST", point_value=1, currency="CNY")


def _state_and_ctx(orders, product, timestamp):
    strategy = orders[0].strategy
    config = StrategyConfig(strategy=strategy, field_values={
        OrderExecutionModule.matching_model: "bar_volume_limited",
        VolumeCapacityMode.liquidity_mode: "volume_participation",
        VolumeCapacityMode.participation_rate: 0.1,
    })
    state = BacktestRunState(strategy_configs={strategy: config})
    state.market_data_store.volume_table = pd.DataFrame({product: [100.0]}, index=[timestamp])
    for order in orders:
        state.order_store.register_order(order)
        order.set("active_market_timestamp", timestamp)
    drafts = [EventDraft(EventKind.ORDER, timestamp, strategy, order) for order in orders]
    ctx = FlowContext(
        timestamp=timestamp,
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
        drafts_by_strategy={strategy: drafts},
    )
    return state, ctx


def test_same_side_orders_share_one_bar_capacity_reduce_first():
    timestamp = pd.Timestamp("2024-01-01 09:01")
    strategy = Strategy(alias="S")
    product = _product()
    close = Order(
        product, timestamp, -8.0, -8.0, strategy,
        order_id="close", offset=OrderOffset.CLOSE,
    )
    opening = Order(
        product, timestamp, -8.0, -8.0, strategy,
        order_id="open", offset=OrderOffset.OPEN,
    )
    state, ctx = _state_and_ctx([opening, close], product, timestamp)

    allocate_order_capacity(state, ctx, VolumeCapacityMode, OrderExecutionModule)

    assert close.quantity == -8.0
    assert opening.quantity == -2.0
    key = next(iter(state.order_store.capacity_consumed_by_key))
    assert state.order_store.capacity_consumed_by_key[key] == 10.0


def test_volume_snapshot_is_loaded_once_per_timestamp(monkeypatch):
    timestamp = pd.Timestamp("2024-01-01 09:01")
    strategy = Strategy(alias="S")
    product = _product()
    orders = [
        Order(product, timestamp, 3.0, 3.0, strategy, order_id=f"O{index}")
        for index in range(2)
    ]
    state, ctx = _state_and_ctx(orders, product, timestamp)
    calls = 0

    def counted(_state, _timestamp):
        nonlocal calls
        calls += 1
        return {product: 100.0}

    monkeypatch.setattr(
        "tools.testers.backtest.modules.execution_capacity.matching.current_volume_at",
        counted,
    )
    allocate_order_capacity(state, ctx, VolumeCapacityMode, OrderExecutionModule)

    assert calls == 1


def test_one_order_carries_partial_fills_across_completed_bars():
    index = pd.date_range("2024-01-01 09:01", periods=4, freq="1min")
    strategy = Strategy(alias="carry")
    product = _product()
    config = StrategyConfig(strategy=strategy, field_values={
        OrderExecutionModule.matching_model: "bar_volume_limited",
        VolumeCapacityMode.liquidity_mode: "volume_participation",
        VolumeCapacityMode.participation_rate: 0.1,
    })
    state = BacktestRunState(strategy_configs={strategy: config})
    state.market_data_store.volume_table = pd.DataFrame({product: [30.0] * 4}, index=index)
    state.market_data_store.market_price_tables = {
        "close": pd.DataFrame({product: [10.0] * 4}, index=index),
    }
    ledger = state.ledger_for_strategy(strategy)
    set_cash_for_ledger_pool(
        state,
        ledger,
        DataMoney.from_major(1_000.0, currency="CNY", use_minor_units=False),
    )
    order = Order(
        product,
        index[0],
        10.0,
        10.0,
        strategy,
        order_id="carry-order",
        offset=OrderOffset.OPEN,
    )
    state.order_store.register_order(order)
    attempt = create_order_attempt(
        state,
        order,
        timestamp=index[0],
        market_timestamp=index[0],
    )

    for expected_timestamp in index:
        order.set("active_attempt_id", attempt.attempt_id)
        order.set("active_market_timestamp", attempt.market_timestamp)
        draft = EventDraft(EventKind.ORDER, expected_timestamp, strategy, attempt)
        queue = EventQueue()
        ctx = FlowContext(
            timestamp=expected_timestamp,
            event_queue=queue,
            active_strategies=frozenset({strategy}),
            drafts_by_strategy={strategy: [draft]},
        )
        ctx.set(MarketDataModule.current_prices, {product: 10.0})
        ctx.set(MarketDataModule.current_historical_fields, {product: {"VolumeMultiple": 1.0}})
        allocate_order_capacity(state, ctx, VolumeCapacityMode, OrderExecutionModule)
        order.set("effective_price", 10.0)
        order.set("fee_cost", 0.0)
        _apply_order_fill(state, ctx)
        finalize_and_retry_orders(state, ctx, VolumeCapacityMode.retry_events)
        pending = queue.snapshot_head()
        if pending:
            attempt = pending[0].payload

    fills = state.order_store.fills_by_order[order.order_id]
    assert [fill.quantity for fill in fills] == [3.0, 3.0, 3.0, 1.0]
    assert order.filled_quantity == 10.0
    assert order.remaining_quantity == 0.0
