"""Apply and publish execution margin-limit decisions."""

from __future__ import annotations

from tools.testers.backtest.modules.cash_constraint.orders import combine_preserving_reduction
from tools.testers.backtest.modules.order_flow import order_flow_store_for


def apply_execution_scale(state, ctx, components, scale, maximum) -> None:
    from tools.testers.backtest.modules.cash_rescale import _round_execution_scaled_quantity
    from tools.testers.backtest.modules.cash_constraint.fees import estimate_signal_fee
    from tools.testers.backtest.modules.ledger_module import LedgerModule
    from tools.testers.backtest.modules.market_data import MarketDataModule

    store = order_flow_store_for(state)
    prices = ctx.get(MarketDataModule.current_prices, {}) or {}
    for component in components:
        if abs(component.increasing) <= 1e-12:
            continue
        order = component.order
        before = float(order.quantity)
        desired = combine_preserving_reduction(component.reducing, component.increasing, scale)
        rounded = _round_execution_scaled_quantity(state, component.strategy, order, desired)
        if abs(rounded) + 1e-12 < abs(component.reducing):
            rounded = component.reducing
        order.quantity = rounded
        effective_price = order.get("effective_price")
        price = float(
            effective_price
            if effective_price is not None
            else prices[order.instrument]
        )
        order.set("fee_cost", estimate_signal_fee(
            state, ctx, component.strategy, component.ledger, order,
            component.historical,
            component.ledger.get(LedgerModule.positions, {}),
            price,
        ))
        store.record(
            order,
            step="execution_margin_limit",
            label="保证金利用率硬上限",
            timestamp=ctx.timestamp,
            details={
                "before_quantity": before,
                "after_quantity": rounded,
                "scale": scale,
                "max_margin_utilization": maximum,
            },
        )


def publish_execution_summary(ctx, summaries) -> None:
    from tools.testers.backtest.modules.margin_budget import MarginBudgetModule

    ctx.set(MarginBudgetModule.execution_margin_summary, summaries)
    for ref, key in (
        (MarginBudgetModule.cash_pool_equity, "equity"),
        (MarginBudgetModule.projected_margin, "projected_margin"),
        (MarginBudgetModule.gross_leverage, "gross_leverage"),
        (MarginBudgetModule.rounding_error, "rounding_error"),
        (MarginBudgetModule.hard_limit_headroom, "hard_limit_headroom"),
    ):
        ctx.set(ref, {pool: row[key] for pool, row in summaries.items()})
