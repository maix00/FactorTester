"""OrderLifecycleModule — the last Flow in the event_kind=ORDER group.
Reads whatever the standoff chain (margin/fee/liquidity/slippage overrides
on LedgerModule.cash_update, which already ran at lower `order` values)
left on `order.fields`, and finalizes `Order.status`. Produces no new
events — an EventKind.ORDER event resolves entirely within one dispatch.

CANCELLED orders are already terminal (set in place by step 9's
cancellation, before this event ever fires) and are left untouched here;
LedgerModule.cash_update already skips them so they have no ledger effect.
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
        description="确认订单终态",
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
            reject_reason = order.get("reject_reason")
            if reject_reason:
                order.status = OrderStatus.REJECTED
                order.reject_reason = reject_reason
                store.record(
                    order,
                    step="finalize_order",
                    label="订单拒绝",
                    timestamp=ctx.timestamp,
                    details={"reject_reason": str(reject_reason)},
                )
            else:
                order.status = OrderStatus.FILLED
                store.record(order, step="finalize_order", label="订单成交", timestamp=ctx.timestamp)
