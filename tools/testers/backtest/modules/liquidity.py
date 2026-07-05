"""LiquidityModule — caps each product's |deltas| to participation_rate *
volume for that bar as an explicit order-sizing pipeline Flow.

`liquidity_mode="infinite"` (the default) means no liquidity constraint at
all; `liquidity_mode="volume_participation"` caps to `participation_rate *
volume`. Capacity above the cap is simply discarded for this bar, not
deferred to a later one (no queuing/recovery this round, per plan)."""

from __future__ import annotations

from typing import ClassVar

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_construct import OrderConstructModule
from tools.testers.backtest.modules.order_flow import order_flow_store_for


class LiquidityModule(ExecutableModule):
    key: ClassVar[str] = "liquidity"
    label: ClassVar[str] = "流动性"

    liquidity_mode: ClassVar[FieldRef[str]] = FieldRef("liquidity_mode")
    participation_rate: ClassVar[FieldRef[float]] = FieldRef("participation_rate")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "liquidity_mode": FieldDefinition(
            public=True, label="流动性", default="infinite", control_template="select", tab="liquidity",
            options=(("infinite", "不限制"), ("volume_participation", "按成交量占比限制")),
            chip_template="流动性: {value}", tab_label="流动性", tab_order=150,
        ),
        "participation_rate": FieldDefinition(
            public=True, label="参与率", default=0.1, control_template="number", tab="liquidity",
            visible_when={"liquidity_mode": ("volume_participation",)},
            chip_template="参与率: {value}", tab_label="流动性", tab_order=150,
        ),
    }

    cap_order_liquidity: ClassVar[Flow] = Flow(
        "cap_order_liquidity",
        inputs=(OrderConstructModule.sized_deltas, liquidity_mode, participation_rate, MarketDataModule.volume),
        outputs=(OrderConstructModule.deltas,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL,
        order=24,
        after=(OrderConstructModule.round_order_quantity,),
        description="按流动性上限截断下单量",
        compute=lambda state, ctx: _cap_to_liquidity(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (cap_order_liquidity,)


def _cap_to_liquidity(state, ctx) -> None:
    volume = ctx.get(MarketDataModule.volume, {})
    store = order_flow_store_for(state)
    for strategy in ctx.active_strategies:
        config = state.config_for(strategy)
        deltas = ctx.get_for(OrderConstructModule.sized_deltas, strategy, {})
        if config.get(LiquidityModule.liquidity_mode, "infinite") != "volume_participation":
            ctx.set_for(OrderConstructModule.deltas, strategy, deltas)
            continue
        rate = config.get(LiquidityModule.participation_rate, 0.1)
        missing_volume_products = [product for product in deltas if product not in volume]
        if missing_volume_products:
            raise KeyError(
                "volume_participation liquidity requires MarketDataModule volume for "
                + ", ".join(str(getattr(product, "name", product)) for product in missing_volume_products)
            )
        capped = {
            product: _cap_one(quantity, rate * volume[product])
            for product, quantity in deltas.items()
        }
        ctx.set_for(OrderConstructModule.deltas, strategy, capped)
        if capped != deltas:
            store.record_strategy_step(
                strategy,
                timestamp=ctx.timestamp,
                step="liquidity_cap",
                label="按流动性上限截断下单量",
                details={
                    "participation_rate": float(rate),
                    "before": _stringify_deltas(deltas),
                    "after": _stringify_deltas(capped),
                },
            )


def _cap_one(quantity: float, capacity: float) -> float:
    if abs(quantity) <= capacity:
        return quantity
    return capacity if quantity > 0 else -capacity


def _stringify_deltas(deltas: dict) -> dict[str, float]:
    return {
        str(getattr(product, "name", product)): float(quantity)
        for product, quantity in deltas.items()
    }
