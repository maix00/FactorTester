"""LedgerModule — owns the Ledger field schema (cash/positions) AND the
mandatory baseline economic model (unlimited liquidity, fractional
positions, no margin). EngineModule/TradingRuleModule/FeeModule/etc. are optional layers
stacked on top via FlowOverride; this module's own Flows never depend on
them."""

from __future__ import annotations

from collections import deque
from typing import Any, ClassVar

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.engines.native.ledger import ProductPosition, apply_quantity_delta
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.trading_rule import (
    TradingRuleModule, _resolve_method, _resolve_use_int_position,
)


class LedgerModule(ExecutableModule):
    key: ClassVar[str] = "portfolio_capital"  # matches the existing frontend
        # SettingModule("portfolio_capital", "组合资金", ...) -- same concept
    label: ClassVar[str] = "账本"

    cash: ClassVar[FieldRef[Any]] = FieldRef("cash")
    positions: ClassVar[FieldRef[Any]] = FieldRef("positions")
    equity: ClassVar[FieldRef[float]] = FieldRef("equity")
    initial_capital_major: ClassVar[FieldRef[float]] = FieldRef("initial_capital_major")
    base_currency: ClassVar[FieldRef[str]] = FieldRef("base_currency")
    currency_conversion_fee_rate: ClassVar[FieldRef[float]] = FieldRef("currency_conversion_fee_rate")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "initial_capital_major": FieldDefinition(
            public=True, label="初始资金", control_template="number", default=100_000_000.0, tab="capital",
            chip_template="初始资金: {value}", tab_label="资金", tab_order=50,
        ),
        "base_currency": FieldDefinition(
            public=True, label="币种", control_template="select", default="CNY", tab="capital",
            chip_template="币种: {value}", tab_label="资金", tab_order=50,
        ),
        "currency_conversion_fee_rate": FieldDefinition(
            public=True, label="换汇费率", control_template="number", default=0.0, tab="capital",
            minimum=0.0, step=0.000001,
            chip_template="换汇费率: {value}", tab_label="资金", tab_order=50,
        ),
    }

    initialize_ledgers: ClassVar[Flow] = Flow(
        "initialize_ledgers",
        inputs=(EngineModule.engine_mode, TradingRuleModule.accounting_mode, TradingRuleModule.cost_basis_method,
                 TradingRuleModule.use_int_position, ProductSelectionModule.products),
        outputs=(cash, positions),
        phase=Phase.PRE_REPLAY, order=35,
        compute=lambda account, ctx: _initialize_ledgers(account, ctx),
    )
    equity_on_signal: ClassVar[Flow] = Flow(
        "equity_on_signal", inputs=(MarketDataModule.current_prices, cash, positions),
        outputs=(equity,), phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        order=10, compute=lambda account, ctx: _basic_equity(account, ctx),
    )
    cash_update: ClassVar[Flow] = Flow(
        "cash_update", inputs=(MarketDataModule.current_prices,), outputs=(positions, cash),
        phase=Phase.PER_EVENT, event_kind=EventKind.ORDER, order=10,
        compute=lambda account, ctx: _basic_cash_update(account, ctx),
    )
    equity_on_order: ClassVar[Flow] = Flow(
        "equity_on_order", inputs=(MarketDataModule.current_prices, cash, positions),
        outputs=(equity,), phase=Phase.PER_EVENT, event_kind=EventKind.ORDER,
        order=900, after=(cash_update,), compute=lambda account, ctx: _basic_equity(account, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (
        initialize_ledgers, equity_on_signal, cash_update, equity_on_order,
    )


def _initialize_ledgers(account, ctx) -> None:
    from tools.testers.backtest.engines.native.ledger import Ledger

    for strategy, strategy_config in account.strategy_configs.items():
        initial_capital = strategy_config.get(LedgerModule.initial_capital_major, 0.0)
        base_currency = strategy_config.get(LedgerModule.base_currency, "CNY")
        ledger = Ledger(strategy=strategy, base_currency=base_currency)
        ledger.set(LedgerModule.cash, DataMoney.from_major(
            initial_capital, currency=base_currency, use_minor_units=False))

        use_int = _resolve_use_int_position(strategy_config)
        initial_quantity = 0 if use_int else 0.0
        zero_equity_occupied = DataMoney.from_major(0, currency=base_currency, use_minor_units=False)

        positions: dict = {}
        products = ctx.get_for(ProductSelectionModule.products, strategy, frozenset())
        for product in products:
            method = _resolve_method(strategy_config, product)
            if method == "WeightAverage":
                positions[product] = ProductPosition(
                    quantity=initial_quantity, average_cost=0.0, equity_occupied=zero_equity_occupied)
            elif method in ("FIFO", "LIFO", "HIFO"):
                positions[product] = ProductPosition(
                    quantity=initial_quantity, lots=deque(), equity_occupied=zero_equity_occupied)
            else:  # DailyMarkToMarket
                positions[product] = ProductPosition(
                    quantity=initial_quantity, equity_occupied=zero_equity_occupied)
        ledger.set(LedgerModule.positions, positions)
        account.ledgers[strategy] = ledger


def _basic_equity(account, ctx) -> None:
    prices = ctx.get(MarketDataModule.current_prices)
    for strategy in ctx.active_strategies:
        ledger = account.ledgers[strategy]
        cash = ledger.get(LedgerModule.cash)
        positions = ledger.get(LedgerModule.positions, {})
        market_value = sum(entry.quantity * prices[product] for product, entry in positions.items())
        ctx.set_for(LedgerModule.equity, strategy, cash.to_major() + market_value)


def _basic_cash_update(account, ctx) -> None:
    """`order.fields["effective_price"]`/`order.fields["fee_cost"]` are
    optional hooks for FlowOverride layers (SlippageModule/FeeModule,
    step 6) to set before this base computation runs — absent either, this
    degrades to "trade at the unadjusted market price, no fee", the same
    "field value is the parameter" pattern as TradingRuleModule's
    margin_mode="none".

    A strategy can have several simultaneous orders in this batch (one per
    product being rebalanced at this timestamp) -- all of them are applied
    to the same Ledger, fetched once per strategy rather than once per
    order to avoid repeated dict lookups."""
    from tools.testers.backtest.engines.native.order import OrderStatus

    prices = ctx.get(MarketDataModule.current_prices)
    for strategy in ctx.active_strategies:
        ledger = account.ledgers[strategy]
        positions = ledger.get(LedgerModule.positions, {})
        cash = ledger.get(LedgerModule.cash)
        for order in ctx.payloads_for(strategy):
            if order.status == OrderStatus.CANCELLED:
                continue  # superseded before it fired (step 9) -- no ledger effect
            entry = positions.setdefault(order.instrument, ProductPosition())
            apply_quantity_delta(entry, order.quantity)
            price = order.get("effective_price", prices[order.instrument])
            fee_cost = order.get("fee_cost", 0.0)
            trade_cost = DataMoney.from_major(
                order.quantity * price + fee_cost, currency=cash.currency, use_minor_units=cash.use_minor_units)
            cash = cash - trade_cost
        ledger.set(LedgerModule.positions, positions)
        ledger.set(LedgerModule.cash, cash)
