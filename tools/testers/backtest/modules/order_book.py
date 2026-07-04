"""OrderBookModule — turns target_weights into raw trade deltas, then into
concrete Order objects after optional sizing/liquidity/cash pipeline steps.

Owns the base "how much should we trade before execution constraints" decision;
LedgerModule owns account state, OrderLifecycleModule owns "did this Order's
standoff chain accept/reject it" — distinct concerns, distinct modules."""

from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.engines.native.order import Order
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    contract_multiplier_from_fields,
    is_product_tradable,
)
from tools.testers.backtest.modules.order_flow import order_flow_store_for
from tools.testers.backtest.modules.target import TargetStrategyModule

_TARGET_WEIGHTS_REF: FieldRef[Any] = TargetStrategyModule.target_weights


class OrderBookModule(ExecutableModule):
    key: ClassVar[str] = "order_book"
    label: ClassVar[str] = "订单"

    raw_deltas: ClassVar[FieldRef[Any]] = FieldRef("raw_deltas")  # target-minus-position before execution constraints
    sized_deltas: ClassVar[FieldRef[Any]] = FieldRef("sized_deltas")  # after lot-size/position-sizing constraints
    deltas: ClassVar[FieldRef[Any]] = FieldRef("deltas")    # dict[Product, float], ctx-scoped final executable deltas
    orders: ClassVar[FieldRef[Any]] = FieldRef("orders")    # list[Order], ctx-scoped

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "raw_deltas": FieldDefinition(public=False),
        "sized_deltas": FieldDefinition(public=False),
        "deltas": FieldDefinition(public=False),
        "orders": FieldDefinition(public=False),
    }

    size_order: ClassVar[Flow] = Flow(
        "size_order",
        inputs=(_TARGET_WEIGHTS_REF, LedgerModule.equity,
                 MarketDataModule.current_prices, MarketDataModule.current_historical_fields,
                 MarketDataModule.current_tradable_status,
                 LedgerModule.positions),
        outputs=(raw_deltas,), phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        order=20, after=(LedgerModule.equity_on_signal,),
        description="计算原始目标下单量",
        compute=lambda state, ctx: _basic_size_order(state, ctx),
    )
    construct_orders: ClassVar[Flow] = Flow(
        "construct_orders", inputs=(deltas,), outputs=(orders,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        order=30, after=(size_order,),
        description="构造订单",
        compute=lambda state, ctx: _construct_orders(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (size_order, construct_orders)


def _basic_size_order(state, ctx) -> None:
    prices = ctx.get(MarketDataModule.current_prices)
    tradable_status = ctx.get(MarketDataModule.current_tradable_status, None)
    for strategy in ctx.active_strategies:
        ledger = state.ledger_for_strategy(strategy)
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
            price = prices.get(product) if isinstance(prices, dict) else None
            if not is_product_tradable(tradable_status, product, prices):
                _record_untradable_target_skip(state, strategy, product, ctx.timestamp)
                continue
            if price is None:
                _record_untradable_target_skip(state, strategy, product, ctx.timestamp)
                continue
            multiplier = contract_multiplier_from_fields(historical_fields, product)
            target_quantity = target_weights.get(product, 0.0) * equity / (float(price) * multiplier)
            deltas[product] = target_quantity - getattr(positions.get(product), "quantity", 0.0)
        ctx.set_for(OrderBookModule.raw_deltas, strategy, deltas)


def _construct_orders(state, ctx) -> None:
    store = order_flow_store_for(state)
    for strategy in ctx.active_strategies:
        deltas = ctx.get_for(OrderBookModule.deltas, strategy, {})
        orders = []
        for product, quantity in deltas.items():
            if quantity == 0:
                continue
            order = Order(
                instrument=product,
                timestamp=ctx.timestamp,
                quantity=quantity,
                intent_quantity=quantity,
                strategy=strategy,
                order_id=store.next_order_id(strategy, ctx.timestamp),
            )
            store.record(order, step="construct_order", label="构造订单")
            orders.append(order)
        ctx.set_for(OrderBookModule.orders, strategy, orders)


def _record_untradable_target_skip(state, strategy, product, timestamp) -> None:
    product_name = str(getattr(product, "name", product))
    product_desc = str(getattr(product, "desc", "") or "")
    display = f"{product_name}({product_desc})" if product_desc else product_name
    row = {
        "type": "订单",
        "status": "未生成",
        "level": "warning",
        "code": "order_target_skipped_untradable",
        "message": f"{display} 当前不可交易，目标调整未生成订单",
        "detail": (
            f"{display} 在 {timestamp} 缺少有效可交易价格或被可交易状态过滤；"
            "本次目标调整不生成订单，既有持仓保留，等待后续可交易时点。"
        ),
        "details": {
            "strategy": str(getattr(strategy, "alias", strategy)),
            "product": product_name,
            "timestamp": str(timestamp),
        },
    }
    runtime_rows = getattr(state, "runtime_info_rows", None)
    if isinstance(runtime_rows, list):
        if not any(
            isinstance(existing, dict)
            and existing.get("code") == row["code"]
            and existing.get("details") == row["details"]
            for existing in runtime_rows[-50:]
        ):
            runtime_rows.append(row)
    sink = getattr(state, "runtime_info_sink", None)
    emit = getattr(sink, "emit_runtime_info", None)
    if callable(emit):
        emit(row["message"], level=row["level"], code=row["code"], details=row["details"], row=row)
