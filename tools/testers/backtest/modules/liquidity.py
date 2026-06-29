"""LiquidityModule — caps each product's |deltas| to participation_rate *
volume for that bar, applied as a FlowOverride on OrderBookModule.size_order.

`liquidity_mode="infinite"` (the default) means no liquidity constraint at
all; `liquidity_mode="volume_participation"` caps to `participation_rate *
volume`. Capacity above the cap is simply discarded for this bar, not
deferred to a later one (no queuing/recovery this round, per plan)."""

from __future__ import annotations

from typing import ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import FlowOverride
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_book import OrderBookModule


class LiquidityModule(ExecutableModule):
    key: ClassVar[str] = "liquidity"
    label: ClassVar[str] = "流动性"

    liquidity_mode: ClassVar[FieldRef[str]] = FieldRef("liquidity_mode")
    participation_rate: ClassVar[FieldRef[float]] = FieldRef("participation_rate")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "liquidity_mode": FieldDefinition(
            public=True, default="infinite", control_template="select", tab="liquidity",
            options=(("infinite", "不限制"), ("volume_participation", "按成交量占比限制")),
        ),
        "participation_rate": FieldDefinition(
            public=True, default=0.1, control_template="number", tab="liquidity",
            visible_when={"liquidity_mode": ("volume_participation",)},
        ),
    }

    overrides: ClassVar[tuple[FlowOverride, ...]] = (
        FlowOverride(
            flow_names=(OrderBookModule.size_order.name,),
            extra_inputs=(liquidity_mode, participation_rate, MarketDataModule.volume),
            compute=lambda account, ctx, base_compute: _cap_to_liquidity(account, ctx, base_compute),
        ),
    )


def _cap_to_liquidity(account, ctx, base_compute) -> None:
    base_compute(account, ctx)
    volume = ctx.get(MarketDataModule.volume, {})
    for strategy in ctx.active_strategies:
        config = account.config_for(strategy)
        if config.get(LiquidityModule.liquidity_mode, "infinite") != "volume_participation":
            continue
        rate = config.get(LiquidityModule.participation_rate, 0.1)
        deltas = ctx.get_for(OrderBookModule.deltas, strategy, {})
        capped = {
            product: _cap_one(quantity, rate * volume.get(product, 0.0))
            for product, quantity in deltas.items()
        }
        ctx.set_for(OrderBookModule.deltas, strategy, capped)


def _cap_one(quantity: float, capacity: float) -> float:
    if abs(quantity) <= capacity:
        return quantity
    return capacity if quantity > 0 else -capacity
