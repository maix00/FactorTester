"""PositionSizingModule — rounds OrderBookModule.raw_deltas to each product's
minimum tradeable lot size as an explicit sizing pipeline Flow.

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

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.market_data import MarketDataModule, market_data_store_for
from tools.testers.backtest.modules.order_book import OrderBookModule
from tools.testers.backtest.modules.order_flow import order_flow_store_for


class PositionSizingModule(ExecutableModule):
    key: ClassVar[str] = "order_sizing"
    label: ClassVar[str] = "开单"

    quantity_rounding_policy: ClassVar[FieldRef[str]] = FieldRef("quantity_rounding_policy")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "quantity_rounding_policy": FieldDefinition(
            public=True, label="数量取整", default="floor_to_lot", control_template="select", tab="order",
            options=(("floor_to_lot", "按最小买入手数向下取整"), ("nearest_lot", "按最小买入手数四舍五入")),
            chip_template="数量取整: {value}", tab_label="订单执行", tab_order=120,
        ),
    }

    round_order_quantity: ClassVar[Flow] = Flow(
        "round_order_quantity",
        inputs=(OrderBookModule.raw_deltas, MarketDataModule.lot_sizes, quantity_rounding_policy),
        outputs=(OrderBookModule.sized_deltas,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL,
        order=22,
        after=(OrderBookModule.size_order,),
        description="按最小买入手数取整",
        compute=lambda state, ctx: _round_to_lot_sizes(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (round_order_quantity,)


def _round_to_lot_sizes(state, ctx) -> None:
    # MarketDataModule.lot_sizes is only ever ctx.set() once, during
    # PRE_REPLAY's _publish_raw_market_data -- PER_EVENT/SIGNAL dispatch runs
    # on a fresh FlowContext (its own empty _values dict), so ctx.get here
    # would always silently return the {} default and lot rounding would
    # never actually apply. lot_sizes is time-invariant per run (unlike
    # current_prices/volume which are legitimately re-published every SIGNAL
    # event), so it belongs on the persistent MarketDataStore, not per-event ctx.
    lot_sizes = ctx.get(MarketDataModule.lot_sizes, None)
    if not lot_sizes:
        lot_sizes = market_data_store_for(state).raw_input.get("lot_sizes") or {}
    store = order_flow_store_for(state)
    for strategy in ctx.active_strategies:
        policy = state.config_for(strategy).get(PositionSizingModule.quantity_rounding_policy, "floor_to_lot")
        deltas = ctx.get_for(OrderBookModule.raw_deltas, strategy, {})
        rounded = {
            product: _round_one(quantity, lot_sizes.get(product), policy)
            for product, quantity in deltas.items()
        }
        ctx.set_for(OrderBookModule.sized_deltas, strategy, rounded)
        if rounded != deltas:
            store.record_strategy_step(
                strategy,
                timestamp=ctx.timestamp,
                step="quantity_rounding",
                label="按最小买入手数取整",
                details={"policy": policy, "before": _stringify_deltas(deltas), "after": _stringify_deltas(rounded)},
            )


def _round_one(quantity: float, lot_size: float | None, policy: str) -> float:
    if not lot_size:
        return quantity
    # +1e-12 guards against floating-point representation landing just under
    # a whole lot (e.g. 239.99999999999997 should floor to 240, not 239) --
    # the same epsilon convention runners/common.py's target_quantities and
    # capacity_limited_deltas already use; without it, real price data can
    # floor down one whole lot short at an exact-lot boundary (surfaced by
    # test_framework_consistency_real_data.py diverging from the worker path
    # by exactly one lot).
    lots = abs(quantity) / lot_size + 1e-12
    rounded_lots = math.floor(lots) if policy == "floor_to_lot" else round(lots)
    sign = 1.0 if quantity > 0 else (-1.0 if quantity < 0 else 0.0)
    return sign * rounded_lots * lot_size


def _stringify_deltas(deltas: dict) -> dict[str, float]:
    return {
        str(getattr(product, "name", product)): float(quantity)
        for product, quantity in deltas.items()
    }
