"""Build and solve execution margin-limit projections."""

from __future__ import annotations

from tools.testers.backtest.modules.cash_constraint.orders import split_reducing_and_increasing
from tools.testers.backtest.modules.ledger_module import _ledger_equity
from tools.testers.backtest.modules.market_data import MarketDataModule

from .simulation import OrderComponent, project_components


def order_components(entries, positions) -> list[OrderComponent]:
    result = []
    for strategy, order, ledger, historical in entries:
        entry = positions[id(ledger)].get(order.instrument)
        prior = float(getattr(entry, "quantity", 0.0) or 0.0)
        reducing, increasing = split_reducing_and_increasing(prior, float(order.quantity))
        result.append(OrderComponent(strategy, order, ledger, historical, reducing, increasing))
    return result


def pool_equity(state, ctx, entries, cash_major: float) -> float:
    # ORDER events expose ``current_prices`` using the requested execution
    # basis (for example next open), which may contain only the instruments
    # with an executable row at that future price timestamp.  Existing
    # portfolio equity must instead use the causal current traded/close view;
    # settlement prices belong exclusively to the DMTM flow.  The order's
    # effective execution price is still used by ``_apply_quantity`` below for
    # the incremental projection.
    snapshot = ctx.get(MarketDataModule.current_market_snapshot, {}) or {}
    prices = snapshot.get("close") if isinstance(snapshot, dict) else None
    prices = prices or ctx.get(MarketDataModule.current_prices, {}) or {}
    unique = {}
    for strategy, _order, ledger, _historical in entries:
        unique.setdefault(id(ledger), (strategy, ledger))
    return cash_major + sum(
        _ledger_equity(state, ctx, strategy, ledger, prices) - cash_major
        for strategy, ledger in unique.values()
    )


def find_scale(state, ctx, components, reduced, maximum) -> float:
    low, high = 0.0, 1.0
    for _ in range(48):
        mid = (low + high) / 2.0
        result = project_components(
            state, ctx, components, reduced.positions, reduced.cash,
            reduced.equity, reduced.margin, include_reducing=False, increasing_scale=mid,
        )
        if result.utilization <= maximum:
            low = mid
        else:
            high = mid
    return low
