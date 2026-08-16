"""Order construction field schema and compatibility exports."""

from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.fields import (
    ExecutableModule,
    FieldDefinition,
    FieldRef,
)
from tools.testers.backtest.modules.order_construction.build import construct_orders
from tools.testers.backtest.modules.order_construction.diagnostics import (
    record_untradable_target_skip as _record_untradable_target_skip,
)
from tools.testers.backtest.modules.order_construction.flows import (
    build_order_construct_flows,
)
from tools.testers.backtest.modules.order_construction.rounding import (
    default_round_order_quantity,
    effective_lot_size as _effective_lot_size,
    round_to_lot_sizes,
    stringify_deltas as _stringify_deltas,
)
from tools.testers.backtest.modules.order_construction.sizing import (
    basic_size_order,
    strategy_trade_intent as _strategy_trade_intent,
)


class OrderConstructModule(ExecutableModule):
    key: ClassVar[str] = "order_construct"
    label: ClassVar[str] = "订单构造"

    raw_deltas: ClassVar[FieldRef[Any]] = FieldRef("raw_deltas")
    sized_deltas: ClassVar[FieldRef[Any]] = FieldRef("sized_deltas")
    deltas: ClassVar[FieldRef[Any]] = FieldRef("deltas")
    orders: ClassVar[FieldRef[Any]] = FieldRef("orders")
    quantity_rounding_policy: ClassVar[FieldRef[str]] = FieldRef(
        "quantity_rounding_policy",
    )
    fields: ClassVar[dict[str, FieldDefinition]] = {
        "raw_deltas": FieldDefinition(public=False, display_value_kind="delta_table"),
        "sized_deltas": FieldDefinition(public=False, display_value_kind="delta_table"),
        "deltas": FieldDefinition(public=False, display_value_kind="delta_table"),
        "orders": FieldDefinition(public=False, display_value_kind="order_table"),
        "quantity_rounding_policy": FieldDefinition(
            public=True, label="数量取整", default="floor_to_lot",
            editor="select", tab="order",
            options=(
                ("floor_to_lot", "按最小买入手数向下取整"),
                ("nearest_lot", "按最小买入手数四舍五入"),
            ),
            chip_template="数量取整: {value}", tab_label="订单执行", tab_order=120,
            help_text=(
                "OrderConstruct 的默认 sizing hook；"
                "自定义 StrategyBook 可以覆盖 sizing 逻辑。"
            ),
        ),
    }


(
    OrderConstructModule.size_order,
    OrderConstructModule.round_order_quantity,
    OrderConstructModule.construct_orders,
) = build_order_construct_flows(OrderConstructModule)
OrderConstructModule.flows = (
    OrderConstructModule.size_order,
    OrderConstructModule.round_order_quantity,
    OrderConstructModule.construct_orders,
)


def _basic_size_order(state, ctx) -> None:
    basic_size_order(state, ctx, OrderConstructModule)


def _round_to_lot_sizes(state, ctx) -> None:
    round_to_lot_sizes(state, ctx, OrderConstructModule)


def _construct_orders(state, ctx) -> None:
    construct_orders(state, ctx, OrderConstructModule)
