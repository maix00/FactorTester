from __future__ import annotations

import uuid

import pandas as pd

from tools.products.Product import Product
from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.ledger import ledger_identity
from tools.testers.backtest.engines.native.order import Order, OrderOffset
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.cash_pool import cash_for_ledger
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.ledger_module import (
    LedgerModule,
    _apply_order_fill,
    _initialize_ledgers,
)
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.trading_rule import TradingRuleModule


INITIAL_CASH = 100_000.0
QUANTITY = 3.0
MULTIPLIER = 10.0
OPEN_PRICE = 100.0
FEE_PER_FILL = 2.0


def short_account(*, margin: bool, daily_mtm: bool) -> tuple[
    BacktestRunState, Strategy, Product,
]:
    strategy = Strategy(alias="short-gold")
    product = Product(
        name=f"SHORT-{uuid.uuid4().hex}",
        point_value=1,
        currency="CNY",
    )
    config = StrategyConfig(strategy=strategy, field_values={
        LedgerModule.initial_capital_major: INITIAL_CASH,
        LedgerModule.base_currency: "CNY",
        EngineModule.engine_mode: "custom",
        TradingRuleModule.accounting_mode: "Custom",
        TradingRuleModule.cost_basis_method: "FIFO",
        TradingRuleModule.daily_mark_to_market_enabled: daily_mtm,
    })
    state = BacktestRunState(strategy_configs={strategy: config})
    state.ledger_configs[ledger_identity(f"private:{strategy.alias}")] = LedgerConfig(
        accounting_mode="Custom",
        cost_basis_method="FIFO",
        daily_mark_to_market_enabled=daily_mtm,
        fee_mode="custom",
        margin_mode="fixed" if margin else "none",
        fixed_margin_ratio=0.1 if margin else None,
    )
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))
    _initialize_ledgers(state, ctx)
    return state, strategy, product


def historical_fields(
    product: Product,
    *,
    settlement: float | None = None,
) -> dict:
    values = {
        "VolumeMultiple": MULTIPLIER,
        "LongMarginRatioByMoney": 0.1,
        "ShortMarginRatioByMoney": 0.1,
    }
    if settlement is not None:
        values["SettlementPrice"] = settlement
    return {product: values}


def fill_order(
    state: BacktestRunState,
    strategy: Strategy,
    product: Product,
    *,
    timestamp: str,
    quantity: float,
    price: float,
    fee: float,
    offset: OrderOffset,
) -> Order:
    ts = pd.Timestamp(timestamp)
    order = Order(
        instrument=product,
        timestamp=ts,
        quantity=quantity,
        intent_quantity=quantity,
        strategy=strategy,
        offset=offset,
    )
    order.set("effective_price", price)
    order.set("fee_cost", fee)
    ctx = FlowContext(
        timestamp=ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
        drafts_by_strategy={
            strategy: [EventDraft(EventKind.ORDER, ts, strategy, order)],
        },
    )
    ctx.set(MarketDataModule.current_prices, {product: price})
    ctx.set(
        MarketDataModule.current_historical_fields,
        historical_fields(product, settlement=price),
    )
    _apply_order_fill(state, ctx)
    return order


def cash_major(state: BacktestRunState, strategy: Strategy) -> float:
    value = cash_for_ledger(state, state.ledger_for_strategy(strategy))
    assert value is not None
    return value.to_major()
