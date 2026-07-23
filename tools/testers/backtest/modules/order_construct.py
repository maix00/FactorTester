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
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    contract_multiplier_from_fields,
    is_product_tradable,
    market_data_store_for,
)
from tools.testers.backtest.modules.order_flow import order_flow_store_for
from tools.testers.backtest.modules.order_lifecycle import reconcile_target_delta
from tools.testers.backtest.modules.runtime_info import (
    product_display,
    product_display_text,
    record_runtime_info,
)
from tools.testers.backtest.modules.strategy_book import (
    apply_order_sizing_policy,
    ledger_for_strategy_product,
    positions_for_strategy_ledgers,
)
from tools.testers.backtest.modules.target import OrderDeltaIntent, TargetStrategyModule, TargetWeightIntent
from tools.testers.backtest.modules.volume_capacity import VolumeCapacityMode
from tools.testers.backtest.modules.trading_rule import TradingRuleModule, _resolve_use_int_position

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
        "raw_deltas": FieldDefinition(public=False, display_value_kind="delta_table"),
        "sized_deltas": FieldDefinition(public=False, display_value_kind="delta_table"),
        "deltas": FieldDefinition(public=False, display_value_kind="delta_table"),
        "orders": FieldDefinition(public=False, display_value_kind="order_table"),
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
                 MarketDataModule.volume,
                 VolumeCapacityMode.liquidity_mode,
                 VolumeCapacityMode.participation_rate,
                 LedgerModule.positions),
        outputs=(raw_deltas,), phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        order=20, after=(LedgerModule.equity_on_signal,),
        description="计算原始目标下单量",
        compute=lambda state, ctx: _basic_size_order(state, ctx),
    )
    round_order_quantity: ClassVar[Flow] = Flow(
        "round_order_quantity",
        inputs=(
            raw_deltas,
            MarketDataModule.lot_sizes,
            quantity_rounding_policy,
            EngineModule.engine_mode,
            TradingRuleModule.accounting_mode,
            TradingRuleModule.use_int_position,
        ),
        outputs=(sized_deltas, deltas),
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
        equity = ctx.get_for(LedgerModule.equity, strategy)
        historical_fields = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        positions = positions_for_strategy_ledgers(state, strategy)
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
            ledger = ledger_for_strategy_product(state, strategy, product)
            ledger_positions = ledger.get(LedgerModule.positions, {})
            multiplier = contract_multiplier_from_fields(historical_fields, product, state=state, timestamp=ctx.timestamp)
            target_quantity = target_weights.get(product, 0.0) * equity / (float(price) * multiplier)
            actual_quantity = float(getattr(ledger_positions.get(product), "quantity", 0.0) or 0.0)
            deltas[product] = reconcile_target_delta(
                state,
                strategy,
                product,
                actual_quantity=actual_quantity,
                target_quantity=target_quantity,
                timestamp=ctx.timestamp,
            )
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
            product: default_round_order_quantity(
                quantity,
                _effective_lot_size(state, strategy, product, lot_sizes),
                policy,
            )
            for product, quantity in deltas.items()
        }
        ctx.set_for(OrderConstructModule.sized_deltas, strategy, rounded)
        ctx.set_for(OrderConstructModule.deltas, strategy, rounded)
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


def _effective_lot_size(state, strategy, product, lot_sizes: dict) -> float | None:
    lot_size = lot_sizes.get(product)
    if lot_size:
        return float(lot_size)
    config = state.config_for(strategy)
    ledger = ledger_for_strategy_product(state, strategy, product)
    if _resolve_use_int_position(config, state.ledger_config_for(ledger)):
        return 1.0
    return None


def _construct_orders(state, ctx) -> None:
    store = order_flow_store_for(state)
    for strategy in ctx.active_strategies:
        deltas = ctx.get_for(OrderConstructModule.deltas, strategy, {})
        orders = []
        for product in sorted(
            deltas,
            key=lambda item: str(getattr(item, "name", item)),
        ):
            quantity = deltas[product]
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
            state.order_store.register_order(order)
            store.record(order, step="construct_order", label="构造订单")
            orders.append(order)
        ctx.set_for(OrderConstructModule.orders, strategy, orders)


def _record_untradable_target_skip(state, strategy, product, timestamp) -> None:
    strategy_name = str(getattr(strategy, "alias", strategy))
    product_info = product_display(product)
    display = product_display_text(product_info)
    reason = "缺少有效可交易价格或被可交易状态过滤"
    aggregation_key = f"{strategy_name}|{product_info['name']}|{reason}"
    ts_text = str(timestamp)
    start, end, count, seen_timestamps = _existing_untradable_target_skip_interval(
        state,
        aggregation_key,
    )
    start = min(start, ts_text) if start else ts_text
    end = max(end, ts_text) if end else ts_text
    if ts_text not in seen_timestamps:
        seen_timestamps.add(ts_text)
        count += 1
    details = {
        "strategy": strategy_name,
        "product": product_info["name"],
        "product_desc": product_info["desc"],
        "reason": reason,
        "start": start,
        "end": end,
        "timestamp": end,
        "count": count,
        "_seen_timestamps": sorted(seen_timestamps),
    }
    record_runtime_info(
        state,
        code="order_target_skipped_untradable",
        type="订单",
        status="未生成",
        level="warning",
        message=f"{display} 当前不可交易，目标调整未生成订单",
        detail=(
            f"{display} 在 {start} 到 {end} 期间 {reason}；"
            f"目标调整未生成订单，既有持仓保留，等待后续可交易时点；累计 {count} 次。"
        ),
        details=details,
        aggregation_key=aggregation_key,
    )


def _existing_untradable_target_skip_interval(
    state,
    aggregation_key: str,
) -> tuple[str | None, str | None, int, set[str]]:
    rows = getattr(state, "runtime_info_rows", None)
    if not isinstance(rows, list):
        return None, None, 0, set()
    for row in rows:
        if (
            isinstance(row, dict)
            and row.get("code") == "order_target_skipped_untradable"
            and row.get("aggregation_key") == aggregation_key
        ):
            details = row.get("details") if isinstance(row.get("details"), dict) else {}
            seen_raw = details.get("_seen_timestamps")
            if isinstance(seen_raw, (list, tuple, set)):
                seen = {str(value) for value in seen_raw}
            else:
                seen = set()
                if details.get("start"):
                    seen.add(str(details["start"]))
            return (
                str(details.get("start")) if details.get("start") else None,
                str(details.get("end")) if details.get("end") else None,
                int(details.get("count") or 0),
                seen,
            )
    return None, None, 0, set()


def _stringify_deltas(deltas: dict) -> dict[str, float]:
    return {
        str(getattr(product, "name", product)): float(quantity)
        for product, quantity in deltas.items()
    }
