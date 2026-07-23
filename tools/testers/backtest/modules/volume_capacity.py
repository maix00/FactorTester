"""Execution-stage volume capacity and carried partial fills."""

from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.execution_capacity import allocate_order_capacity
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_execution import OrderExecutionModule
from tools.testers.backtest.modules.order_lifecycle import finalize_and_retry_orders


class VolumeCapacityMode(ExecutableModule):
    key: ClassVar[str] = "volume_capacity"
    label: ClassVar[str] = "成交量容量"

    liquidity_mode: ClassVar[FieldRef[str]] = FieldRef("liquidity_mode")
    participation_rate: ClassVar[FieldRef[float]] = FieldRef("participation_rate")
    capacity_allocations: ClassVar[FieldRef[Any]] = FieldRef("capacity_allocations")
    retry_events: ClassVar[FieldRef[Any]] = FieldRef("retry_events")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "liquidity_mode": FieldDefinition(
            public=True, label="成交量容量", default="infinite", control_template="select", tab="volume_capacity",
            options=(("infinite", "不限制"), ("volume_participation", "按执行 bar 成交量占比限制")),
            chip_template="容量约束: {value}", tab_label="成交量容量", tab_order=150,
        ),
        "participation_rate": FieldDefinition(
            public=True, label="参与率", default=0.1, control_template="number", tab="volume_capacity",
            visible_when={"liquidity_mode": ("volume_participation",)},
            chip_template="参与率: {value}", tab_label="成交量容量", tab_order=150,
        ),
        "capacity_allocations": FieldDefinition(public=False, display_value_kind="capacity_table"),
        "retry_events": FieldDefinition(public=False),
    }

    allocate_capacity: ClassVar[Flow] = Flow(
        "allocate_capacity",
        inputs=(
            liquidity_mode,
            participation_rate,
            OrderExecutionModule.matching_model,
            MarketDataModule.volume,
        ),
        outputs=(capacity_allocations,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.ORDER,
        order=6,
        after=(OrderExecutionModule.resolve_execution_price,),
        description="按执行 bar 容量分配本次成交量",
        event_payload_inputs=("order",),
        compute=lambda state, ctx: allocate_order_capacity(
            state, ctx, VolumeCapacityMode, OrderExecutionModule,
        ),
    )
    finalize_attempts: ClassVar[Flow] = Flow(
        "finalize_attempts",
        inputs=(capacity_allocations,),
        outputs=(retry_events,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.ORDER,
        order=12,
        description="结束本次撮合并登记未成交余量",
        event_payload_inputs=("order",),
        compute=lambda state, ctx: finalize_and_retry_orders(
            state, ctx, VolumeCapacityMode.retry_events,
        ),
    )

    flows: ClassVar[tuple[Flow, ...]] = (allocate_capacity, finalize_attempts)


def apply_volume_capacity_policy(
    state: object,
    ctx: object,
    strategy: object,
    deltas: dict[Any, float],
) -> dict[Any, float]:
    """Compatibility hook: target sizing no longer consumes market capacity."""
    return deltas
