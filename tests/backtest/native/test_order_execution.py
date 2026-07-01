from __future__ import annotations

import uuid

import pandas as pd

from tools.products.Product import Product
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.ledger import AccountState, StrategyConfig
from tools.testers.backtest.engines.native.order import Order
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_execution import OrderExecutionModule, _resolve_execution_price


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def test_execution_price_basis_uses_same_price_timestamp_but_different_columns():
    product = _product()
    idx = pd.date_range("2024-01-01 09:01", periods=2, freq="1min")
    price_ts = idx[1]
    open_strategy = Strategy(alias="open")
    close_strategy = Strategy(alias="close")
    vwap_strategy = Strategy(alias="vwap")
    account = AccountState(strategy_configs={
        open_strategy: StrategyConfig(strategy=open_strategy, field_values={
            OrderExecutionModule.execution_price_basis: "open",
        }),
        close_strategy: StrategyConfig(strategy=close_strategy, field_values={
            OrderExecutionModule.execution_price_basis: "close",
        }),
        vwap_strategy: StrategyConfig(strategy=vwap_strategy, field_values={
            OrderExecutionModule.execution_price_basis: "vwap",
        }),
    })
    account.market_price_tables = {
        "open": pd.DataFrame({product: [10.0, 20.0]}, index=idx),
        "close": pd.DataFrame({product: [11.0, 21.0]}, index=idx),
        "vwap": pd.DataFrame({product: [12.0, 22.0]}, index=idx),
    }
    orders_by_strategy = {}
    drafts_by_strategy = {}
    for strategy in (open_strategy, close_strategy, vwap_strategy):
        order = Order(instrument=product, timestamp=price_ts, quantity=1.0, intent_quantity=1.0, strategy=strategy)
        order.set("price_timestamp", price_ts)
        orders_by_strategy[strategy] = order
        drafts_by_strategy[strategy] = [EventDraft(EventKind.ORDER, price_ts, strategy, order)]
    ctx = FlowContext(
        timestamp=price_ts,
        event_queue=EventQueue(),
        active_strategies=frozenset((open_strategy, close_strategy, vwap_strategy)),
        drafts_by_strategy=drafts_by_strategy,
    )
    ctx.set(MarketDataModule.current_prices, {product: 999.0})

    _resolve_execution_price(account, ctx)

    assert orders_by_strategy[open_strategy].get("effective_price") == 20.0
    assert orders_by_strategy[close_strategy].get("effective_price") == 21.0
    assert orders_by_strategy[vwap_strategy].get("effective_price") == 22.0
