"""OrderLifecycleModule — terminal-order audit for event_kind=ORDER.

The order's real terminal state is produced by the flow that creates it:
cancellation writes CANCELLED, execution/settlement writes REJECTED or FILLED.
This module only records that terminal state and raises if an ORDER event
leaves the pipeline without a terminal status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.engines.native.order import OrderStatus
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.order_flow import order_flow_store_for


@dataclass
class OrderStore:
    pending_orders: dict[Any, Any] = field(default_factory=dict)


class OrderLifecycleModule(ExecutableModule):
    key: ClassVar[str] = "order_lifecycle"
    label: ClassVar[str] = "订单终态"

    finalize_order: ClassVar[Flow] = Flow(
        "finalize_order", inputs=(), outputs=(),
        phase=Phase.PER_EVENT, event_kind=EventKind.ORDER,
        order=950, after=(LedgerModule.equity_on_order,),
        description="记录订单终态",
        compute=lambda state, ctx: _finalize_order(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (finalize_order,)


def _finalize_order(state, ctx) -> None:
    store = order_flow_store_for(state)
    for strategy in ctx.active_strategies:
        for order in ctx.payloads_for(strategy):
            if order.status == OrderStatus.CANCELLED:
                store.record(order, step="finalize_order", label="订单已取消", timestamp=ctx.timestamp)
                continue
            if order.status == OrderStatus.REJECTED:
                store.record(
                    order,
                    step="finalize_order",
                    label="订单拒绝",
                    timestamp=ctx.timestamp,
                    details={"reject_reason": str(order.reject_reason or order.get("reject_reason") or "")},
                )
                continue
            if order.status == OrderStatus.FILLED:
                store.record(order, step="finalize_order", label="订单成交", timestamp=ctx.timestamp)
                continue
            raise RuntimeError(
                f"ORDER event for {order.instrument} finished without terminal status: {order.status}"
            )
