from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.order import Order, OrderStatus
from tools.testers.backtest.engines.native.position import ProductPosition
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.ledger_module import (
    LedgerModule,
    _apply_order_fill,
    _basic_equity,
    _initialize_ledgers,
)
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.product_selection import ProductSelectionModule


INITIAL_CAPITAL = 1_000_000.0


def _product() -> Product:
    return Product(
        name=f"P-{uuid.uuid4().hex}",
        point_value=1,
        currency="CNY",
    )


def _state(*products: Product) -> tuple[BacktestRunState, Strategy]:
    strategy = Strategy(alias="fill-valuation")
    config = StrategyConfig(strategy=strategy, field_values={
        LedgerModule.initial_capital_major: INITIAL_CAPITAL,
        LedgerModule.base_currency: "CNY",
        EngineModule.engine_mode: "basic",
    })
    state = BacktestRunState(strategy_configs={strategy: config})
    init_ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    init_ctx.set_for(
        ProductSelectionModule.products,
        strategy,
        frozenset(products),
    )
    _initialize_ledgers(state, init_ctx)
    return state, strategy


def _order(
    strategy: Strategy,
    product: Product,
    timestamp: pd.Timestamp,
    *,
    quantity: float,
    effective_price: float,
) -> Order:
    order = Order(
        instrument=product,
        timestamp=timestamp,
        quantity=quantity,
        intent_quantity=quantity,
        strategy=strategy,
    )
    order.set("effective_price", effective_price)
    return order


def _settle_and_value(
    state: BacktestRunState,
    strategy: Strategy,
    orders: list[Order],
    *,
    current_prices: dict[Product, float],
    close_prices: dict[Product, float],
) -> FlowContext:
    timestamp = orders[0].timestamp
    ctx = FlowContext(
        timestamp=timestamp,
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
        drafts_by_strategy={
            strategy: [
                EventDraft(EventKind.ORDER, timestamp, strategy, order)
                for order in orders
            ],
        },
    )
    ctx.set(MarketDataModule.current_prices, current_prices)
    ctx.set(
        MarketDataModule.current_market_snapshot,
        {"close": close_prices},
    )
    _apply_order_fill(state, ctx)
    _basic_equity(state, ctx)
    return ctx


def test_new_position_is_valued_at_effective_fill_price():
    product = _product()
    state, strategy = _state(product)
    timestamp = pd.Timestamp("2024-01-01 09:30", tz="Asia/Shanghai")
    order = _order(
        strategy,
        product,
        timestamp,
        quantity=10.0,
        effective_price=11.0,
    )

    ctx = _settle_and_value(
        state,
        strategy,
        [order],
        current_prices={product: 10.0},
        close_prices={product: 9.0},
    )

    assert ctx.get_for(LedgerModule.equity, strategy) == pytest.approx(
        INITIAL_CAPITAL,
    )


def test_same_batch_uses_each_fill_price_and_snapshot_for_untraded_position():
    first, second, held = _product(), _product(), _product()
    state, strategy = _state(first, second, held)
    state.ledger_for_strategy(strategy).get(LedgerModule.positions)[held] = (
        ProductPosition(quantity=10.0)
    )
    timestamp = pd.Timestamp("2024-01-01 09:30", tz="Asia/Shanghai")
    orders = [
        _order(
            strategy,
            first,
            timestamp,
            quantity=10.0,
            effective_price=11.0,
        ),
        _order(
            strategy,
            second,
            timestamp,
            quantity=10.0,
            effective_price=23.0,
        ),
    ]

    ctx = _settle_and_value(
        state,
        strategy,
        orders,
        current_prices={first: 10.0, second: 20.0},
        close_prices={first: 8.0, second: 30.0, held: 7.0},
    )

    assert ctx.get_for(LedgerModule.equity, strategy) == pytest.approx(
        INITIAL_CAPITAL + 70.0,
    )


def test_partial_fill_is_valued_at_actual_fill_price():
    product = _product()
    state, strategy = _state(product)
    timestamp = pd.Timestamp("2024-01-01 09:30", tz="Asia/Shanghai")
    order = _order(
        strategy,
        product,
        timestamp,
        quantity=10.0,
        effective_price=11.0,
    )
    order.quantity = 4.0
    order.set("capacity_limited_attempt", True)
    order.set("attempt_fill_quantity", 4.0)

    ctx = _settle_and_value(
        state,
        strategy,
        [order],
        current_prices={product: 10.0},
        close_prices={product: 9.0},
    )

    fill = state.order_store.fills_by_order[order.order_id][0]
    assert fill.quantity == pytest.approx(4.0)
    assert fill.price == pytest.approx(11.0)
    assert order.status is OrderStatus.PARTIALLY_FILLED
    assert ctx.get_for(LedgerModule.equity, strategy) == pytest.approx(
        INITIAL_CAPITAL,
    )
