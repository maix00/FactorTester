"""OrderExecutionModule — declares order execution controls.

The fields are registered here so the frontend schema is module-owned. Wiring
these options into order construction and matching remains a later execution
layer change.
"""

from __future__ import annotations

from typing import ClassVar

from .base import ExecutableModule, FieldDefinition, FieldRef


class OrderExecutionModule(ExecutableModule):
    key: ClassVar[str] = "order_execution"
    label: ClassVar[str] = "订单执行"

    execution_price_basis: ClassVar[FieldRef[str]] = FieldRef("execution_price_basis")
    order_type: ClassVar[FieldRef[str]] = FieldRef("order_type")
    matching_model: ClassVar[FieldRef[str]] = FieldRef("matching_model")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "execution_price_basis": FieldDefinition(
            public=True, default="open", control_template="select", tab="order",
            options=(("close", "收盘/切片价格"), ("open", "开盘价"), ("vwap", "VWAP")),
            chip_template="价格: {value}", tab_label="订单执行", tab_order=120,
        ),
        "order_type": FieldDefinition(
            public=True, default="market", control_template="select", tab="order",
            options=(("market", "市价单"), ("limit", "限价单")),
            chip_template="订单: {value}", tab_label="订单执行", tab_order=120,
        ),
        "matching_model": FieldDefinition(
            public=True, default="next_bar_full_fill", control_template="select", tab="order",
            options=(
                ("next_bar_full_fill", "下一 bar 全额成交"),
                ("bar_volume_limited", "按 bar 成交量限制"),
            ),
            chip_template="撮合: {value}", tab_label="订单执行", tab_order=120,
        ),
    }
