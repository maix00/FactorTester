"""PositionSizingModule — rounds OrderBookModule.size_order's raw deltas to
each product's minimum tradeable lot size. This is a real FlowOverride
(not a parameter-default-degrades-to-no-op case like TradingRuleModule's
margin/cost-basis fields) because rounding is an algorithm step layered on
top of the base computation, not a value the base computation already
reads.

`quantity_rounding_policy`: "floor_to_lot" (default, matches the old
quantity_rounding_policy default) rounds the magnitude DOWN toward zero --
conservative, never commits to more lots than the unrounded target implied,
so it can never push a trade past the capital/lot constraint that produced
the raw target. "nearest_lot" rounds to the closest lot count (can round up),
matching whichever lot count is numerically closer.
"""

from __future__ import annotations

import math
from typing import ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import FlowOverride
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_book import OrderBookModule


class PositionSizingModule(ExecutableModule):
    key: ClassVar[str] = "order_sizing"
    label: ClassVar[str] = "开单"

    quantity_rounding_policy: ClassVar[FieldRef[str]] = FieldRef("quantity_rounding_policy")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "quantity_rounding_policy": FieldDefinition(
            public=True, default="floor_to_lot", control_template="select", tab="order",
            options=(("floor_to_lot", "按最小买入手数向下取整"), ("nearest_lot", "按最小买入手数四舍五入")),
        ),
    }

    overrides: ClassVar[tuple[FlowOverride, ...]] = (
        FlowOverride(
            flow_names=(OrderBookModule.size_order.name,),
            extra_inputs=(MarketDataModule.lot_sizes, quantity_rounding_policy),
            compute=lambda account, ctx, base_compute: _round_to_lot_sizes(account, ctx, base_compute),
        ),
    )


def _round_to_lot_sizes(account, ctx, base_compute) -> None:
    base_compute(account, ctx)  # compute the base deltas first
    lot_sizes = ctx.get(MarketDataModule.lot_sizes, {})
    for strategy in ctx.active_strategies:
        policy = account.config_for(strategy).get(PositionSizingModule.quantity_rounding_policy, "floor_to_lot")
        deltas = ctx.get_for(OrderBookModule.deltas, strategy, {})
        rounded = {
            product: _round_one(quantity, lot_sizes.get(product), policy)
            for product, quantity in deltas.items()
        }
        ctx.set_for(OrderBookModule.deltas, strategy, rounded)


def _round_one(quantity: float, lot_size: float | None, policy: str) -> float:
    if not lot_size:
        return quantity
    lots = abs(quantity) / lot_size
    rounded_lots = math.floor(lots) if policy == "floor_to_lot" else round(lots)
    sign = 1.0 if quantity > 0 else (-1.0 if quantity < 0 else 0.0)
    return sign * rounded_lots * lot_size
