"""OrderConstructModule — turns strategy trade intents into concrete Orders.

Target weights are one supported intent format, not the only one. Technical
rules can emit direct order-delta intents; StrategyBook can still customize
order sizing around this boundary. LedgerModule owns account state and
settlement.
"""

from __future__ import annotations

import math
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
    market_data_store_for,
)
from tools.testers.backtest.modules.order_flow import order_flow_store_for
from tools.testers.backtest.modules.strategy_book import apply_order_sizing_policy
from tools.testers.backtest.modules.target import OrderDeltaIntent, TargetStrategyModule, TargetWeightIntent

_TARGET_WEIGHTS_REF: FieldRef[Any] = TargetStrategyModule.target_weights


class OrderConstructModule(ExecutableModule):
    key: ClassVar[str] = "order_construct"
    label: ClassVar[str] = "订单构造"

    raw_deltas: ClassVar[FieldRef[Any]] = FieldRef("raw_deltas")  # target-minus-position before execution constraints
    sized_deltas: ClassVar[FieldRef[Any]] = FieldRef("sized_deltas")  # after lot-size/position-sizing constraints
    deltas: ClassVar[FieldRef[Any]] = FieldRef("deltas")    # dict[Product, float], ctx-scoped final executable deltas
    orders: ClassVar[FieldRef[Any]] = FieldRef("orders")    # list[Order], ctx-scoped
    quantity_rounding_policy: ClassVar[FieldRef[str]] = FieldRef("quantity_rounding_policy")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "raw_deltas": FieldDefinition(public=False),
        "sized_deltas": FieldDefinition(public=False),
        "deltas": FieldDefinition(public=False),
        "orders": FieldDefinition(public=False),
        "quantity_rounding_policy": FieldDefinition(
            public=True, label="数量取整", default="floor_to_lot", control_template="select", tab="order",
            options=(("floor_to_lot", "按最小买入手数向下取整"), ("nearest_lot", "按最小买入手数四舍五入")),
            chip_template="数量取整: {value}", tab_label="订单执行", tab_order=120,
            help_text="OrderConstruct 的默认 sizing hook；自定义 StrategyBook 可以覆盖 sizing 逻辑。",
        ),
    }

    size_order: ClassVar[Flow] = Flow(
        "size_order",
        inputs=(TargetStrategyModule.trade_intent, _TARGET_WEIGHTS_REF, LedgerModule.equity,
                 MarketDataModule.current_prices, MarketDataModule.current_historical_fields,
                 MarketDataModule.current_tradable_status,
                 LedgerModule.positions),
        outputs=(raw_deltas,), phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        order=20, after=(LedgerModule.equity_on_signal,),
        description="计算原始目标下单量",
        compute=lambda state, ctx: _basic_size_order(state, ctx),
    )
    round_order_quantity: ClassVar[Flow] = Flow(
        "round_order_quantity",
        inputs=(raw_deltas, MarketDataModule.lot_sizes, quantity_rounding_policy),
        outputs=(sized_deltas,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL,
        order=22,
        after=(size_order,),
        description="按最小买入手数取整",
        compute=lambda state, ctx: _round_to_lot_sizes(state, ctx),
    )
    construct_orders: ClassVar[Flow] = Flow(
        "construct_orders", inputs=(deltas,), outputs=(orders,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        order=30, after=(round_order_quantity,),
        description="构造订单",
        compute=lambda state, ctx: _construct_orders(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (size_order, round_order_quantity, construct_orders)


def _basic_size_order(state, ctx) -> None:
    for strategy in ctx.active_strategies:
        intent = _strategy_trade_intent(ctx, strategy)
        if isinstance(intent, OrderDeltaIntent):
            deltas = apply_order_sizing_policy(state, ctx, strategy, dict(intent.deltas))
            ctx.set_for(OrderConstructModule.raw_deltas, strategy, deltas)
            continue
        prices = ctx.get(MarketDataModule.current_prices)
        tradable_status = ctx.get(MarketDataModule.current_tradable_status, None)
        ledger = state.ledger_for_strategy(strategy)
        equity = ctx.get_for(LedgerModule.equity, strategy)
        historical_fields = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        positions = ledger.get(LedgerModule.positions, {})
        target_weights = dict(intent.weights)
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
        deltas = apply_order_sizing_policy(state, ctx, strategy, deltas)
        ctx.set_for(OrderConstructModule.raw_deltas, strategy, deltas)


def _strategy_trade_intent(ctx, strategy) -> TargetWeightIntent | OrderDeltaIntent:
    intent = ctx.get_for(TargetStrategyModule.trade_intent, strategy, None)
    if isinstance(intent, (TargetWeightIntent, OrderDeltaIntent)):
        return intent
    weights = ctx.get_for(_TARGET_WEIGHTS_REF, strategy, {})
    return TargetWeightIntent(dict(weights), reason="legacy_target_weights")


def _round_to_lot_sizes(state, ctx) -> None:
    # lot_sizes is run-invariant and lives on MarketDataStore; ctx only has it
    # in tests or raw-data paths that explicitly set it on the current context.
    lot_sizes = ctx.get(MarketDataModule.lot_sizes, None)
    if not lot_sizes:
        lot_sizes = market_data_store_for(state).raw_input.get("lot_sizes") or {}
    store = order_flow_store_for(state)
    for strategy in ctx.active_strategies:
        policy = state.config_for(strategy).get(OrderConstructModule.quantity_rounding_policy, "floor_to_lot")
        deltas = ctx.get_for(OrderConstructModule.raw_deltas, strategy, {})
        rounded = {
            product: default_round_order_quantity(quantity, lot_sizes.get(product), policy)
            for product, quantity in deltas.items()
        }
        ctx.set_for(OrderConstructModule.sized_deltas, strategy, rounded)
        if rounded != deltas:
            store.record_strategy_step(
                strategy,
                timestamp=ctx.timestamp,
                step="quantity_rounding",
                label="按最小买入手数取整",
                details={"policy": policy, "before": _stringify_deltas(deltas), "after": _stringify_deltas(rounded)},
            )


def default_round_order_quantity(quantity: float, lot_size: float | None, policy: str) -> float:
    if not lot_size:
        return quantity
    # +1e-12 guards against floating-point representation landing just under
    # a whole lot (e.g. 239.99999999999997 should floor to 240, not 239).
    lots = abs(quantity) / lot_size + 1e-12
    rounded_lots = math.floor(lots) if policy == "floor_to_lot" else round(lots)
    sign = 1.0 if quantity > 0 else (-1.0 if quantity < 0 else 0.0)
    return sign * rounded_lots * lot_size


def _construct_orders(state, ctx) -> None:
    store = order_flow_store_for(state)
    for strategy in ctx.active_strategies:
        deltas = ctx.get_for(OrderConstructModule.deltas, strategy, {})
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
        ctx.set_for(OrderConstructModule.orders, strategy, orders)


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


def _stringify_deltas(deltas: dict) -> dict[str, float]:
    return {
        str(getattr(product, "name", product)): float(quantity)
        for product, quantity in deltas.items()
    }
