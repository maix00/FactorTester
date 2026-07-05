from __future__ import annotations

import uuid

import pandas as pd

from tools.products.Product import Product
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.order import Order
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_execution import OrderExecutionModule, _resolve_execution_price
from tools.traderules import OrderTradeConstraint


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def test_execution_price_uses_next_bar_open_price_timestamp():
    product = _product()
    idx = pd.date_range("2024-01-01 09:01", periods=2, freq="1min")
    price_ts = idx[1]
    open_strategy = Strategy(alias="open")
    account = BacktestRunState(strategy_configs={
        open_strategy: StrategyConfig(strategy=open_strategy, field_values={
            OrderExecutionModule.execution_price_basis: "open",
        }),
    })
    account.market_data_store.market_price_tables = {
        "open": pd.DataFrame({product: [10.0, 20.0]}, index=idx),
    }
    order = Order(instrument=product, timestamp=price_ts, quantity=1.0, intent_quantity=1.0, strategy=open_strategy)
    order.set("price_timestamp", price_ts)
    ctx = FlowContext(
        timestamp=price_ts,
        event_queue=EventQueue(),
        active_strategies=frozenset((open_strategy,)),
        drafts_by_strategy={open_strategy: [EventDraft(EventKind.ORDER, price_ts, open_strategy, order)]},
    )
    ctx.set(MarketDataModule.current_order_constraints, {
        product: OrderTradeConstraint(tradable=True, can_buy=True, can_sell=True)
    })

    _resolve_execution_price(account, ctx)

    assert order.get("execution_price_basis") == "open"
    assert order.get("effective_price") == 20.0
    assert order.get("reject_reason") is None


def test_execution_price_rejects_close_or_vwap_basis():
    product = _product()
    idx = pd.date_range("2024-01-01 09:01", periods=2, freq="1min")
    price_ts = idx[1]
    strategy = Strategy(alias="close")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy, field_values={
            OrderExecutionModule.execution_price_basis: "close",
        }),
    })
    account.market_data_store.market_price_tables = {
        "open": pd.DataFrame({product: [10.0, 20.0]}, index=idx),
        "close": pd.DataFrame({product: [11.0, 21.0]}, index=idx),
    }
    order = Order(instrument=product, timestamp=price_ts, quantity=1.0, intent_quantity=1.0, strategy=strategy)
    order.set("price_timestamp", price_ts)
    ctx = FlowContext(
        timestamp=price_ts,
        event_queue=EventQueue(),
        active_strategies=frozenset((strategy,)),
        drafts_by_strategy={strategy: [EventDraft(EventKind.ORDER, price_ts, strategy, order)]},
    )

    import pytest
    with pytest.raises(ValueError, match="next-bar open"):
        _resolve_execution_price(account, ctx)


def test_execution_constraint_rejects_buy_at_upper_limit_but_keeps_sell_allowed():
    product = _product()
    idx = pd.date_range("2024-01-01 09:01", periods=2, freq="1min")
    price_ts = idx[1]
    strategy = Strategy(alias="limit")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy, field_values={
            OrderExecutionModule.execution_price_basis: "open",
        }),
    })
    account.market_data_store.market_price_tables = {
        "open": pd.DataFrame({product: [10.0, 20.0]}, index=idx),
    }
    buy = Order(instrument=product, timestamp=price_ts, quantity=1.0, intent_quantity=1.0, strategy=strategy)
    buy.set("price_timestamp", price_ts)
    sell = Order(instrument=product, timestamp=price_ts, quantity=-1.0, intent_quantity=-1.0, strategy=strategy)
    sell.set("price_timestamp", price_ts)
    ctx = FlowContext(
        timestamp=price_ts,
        event_queue=EventQueue(),
        active_strategies=frozenset((strategy,)),
        drafts_by_strategy={
            strategy: [
                EventDraft(EventKind.ORDER, price_ts, strategy, buy),
                EventDraft(EventKind.ORDER, price_ts, strategy, sell),
            ]
        },
    )
    ctx.set(MarketDataModule.current_order_constraints, {
        product: OrderTradeConstraint(
            tradable=True,
            can_buy=False,
            can_sell=True,
            reason="触及涨停，买入方向不可成交",
        )
    })

    _resolve_execution_price(account, ctx)

    assert buy.get("reject_reason") == "触及涨停，买入方向不可成交"
    assert sell.get("reject_reason") is None
    assert buy.get("effective_price") == sell.get("effective_price") == 20.0


def test_execution_constraint_rejects_order_when_constraint_entry_missing():
    product = _product()
    idx = pd.date_range("2024-01-01 09:01", periods=2, freq="1min")
    price_ts = idx[1]
    strategy = Strategy(alias="missing-constraint")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy, field_values={
            OrderExecutionModule.execution_price_basis: "open",
        }),
    })
    account.market_data_store.market_price_tables = {
        "open": pd.DataFrame({product: [10.0, 20.0]}, index=idx),
    }
    order = Order(instrument=product, timestamp=price_ts, quantity=1.0, intent_quantity=1.0, strategy=strategy)
    order.set("price_timestamp", price_ts)
    ctx = FlowContext(
        timestamp=price_ts,
        event_queue=EventQueue(),
        active_strategies=frozenset((strategy,)),
        drafts_by_strategy={strategy: [EventDraft(EventKind.ORDER, price_ts, strategy, order)]},
    )
    ctx.set(MarketDataModule.current_order_constraints, {})

    _resolve_execution_price(account, ctx)

    assert order.get("reject_reason") == "缺少订单交易约束"
    assert order.get("effective_price") == 20.0
