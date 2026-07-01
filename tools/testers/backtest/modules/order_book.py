"""OrderBookModule — turns target_weights into deltas (size_order) then
into concrete Order objects (construct_orders). Owns the "how much should
we trade" decision; LedgerModule owns account state, OrderLifecycleModule
owns "did this Order's standoff chain accept/reject it" — three distinct
concerns, three distinct modules."""

from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.engines.native.order import Order
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule, contract_multiplier_from_fields
from tools.testers.backtest.modules.target import TargetStrategyModule

_TARGET_WEIGHTS_REF: FieldRef[Any] = TargetStrategyModule.target_weights


class OrderBookModule(ExecutableModule):
    key: ClassVar[str] = "order_book"
    label: ClassVar[str] = "订单"

    deltas: ClassVar[FieldRef[Any]] = FieldRef("deltas")    # dict[Product, float], ctx-scoped, not persisted in Ledger
    orders: ClassVar[FieldRef[Any]] = FieldRef("orders")    # list[Order], ctx-scoped

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "deltas": FieldDefinition(public=False),
        "orders": FieldDefinition(public=False),
    }

    size_order: ClassVar[Flow] = Flow(
        "size_order",
        inputs=(_TARGET_WEIGHTS_REF, LedgerModule.equity,
                 MarketDataModule.current_prices, MarketDataModule.current_historical_fields,
                 LedgerModule.positions),
        outputs=(deltas,), phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        order=20, after=(LedgerModule.equity_on_signal,),
        description="计算目标下单量",
        compute=lambda account, ctx: _basic_size_order(account, ctx),
    )
    construct_orders: ClassVar[Flow] = Flow(
        "construct_orders", inputs=(deltas,), outputs=(orders,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        order=30, after=(size_order,),
        description="构造订单",
        compute=lambda account, ctx: _construct_orders(account, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (size_order, construct_orders)


def _basic_size_order(account, ctx) -> None:
    prices = ctx.get(MarketDataModule.current_prices)
    for strategy in ctx.active_strategies:
        ledger = account.ledgers[strategy]
        equity = ctx.get_for(LedgerModule.equity, strategy)
        historical_fields = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        target_weights = ctx.get_for(_TARGET_WEIGHTS_REF, strategy, {})
        positions = ledger.get(LedgerModule.positions, {})
        # Must cover every currently-held product, not just target_weights'
        # keys -- a product that dropped out of the target (e.g. fell out
        # of the selected quantile bucket, implicit weight 0) still needs
        # its current quantity sold off, which only happens if it's a key
        # here too.
        all_products = set(target_weights) | set(positions)
        deltas = {}
        for product in all_products:
            multiplier = contract_multiplier_from_fields(historical_fields, product)
            target_quantity = target_weights.get(product, 0.0) * equity / (prices[product] * multiplier)
            deltas[product] = target_quantity - getattr(positions.get(product), "quantity", 0.0)
        ctx.set_for(OrderBookModule.deltas, strategy, deltas)


def _construct_orders(account, ctx) -> None:
    for strategy in ctx.active_strategies:
        deltas = ctx.get_for(OrderBookModule.deltas, strategy, {})
        orders = [
            Order(instrument=product, timestamp=ctx.timestamp, quantity=quantity,
                  intent_quantity=quantity, strategy=strategy)
            for product, quantity in deltas.items() if quantity != 0
        ]
        ctx.set_for(OrderBookModule.orders, strategy, orders)
