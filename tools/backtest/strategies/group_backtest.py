"""Composition helpers for executable quantile-group backtests."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ..event_driven.backtest import StrategyLane
from ..execution.trading import (
    CashAccounting,
    EqualNotionalSizer,
    FillAccounting,
    Ledger,
    MarketState,
    OrderManager,
)
from .group import QuantileGroupStrategy
from .allocation import AllocationInput, WeightAllocator
from .rebalance import RebalanceTrigger


def build_quantile_group_lanes(
    *,
    factor_alias: str,
    strategy_prefix: str,
    instruments: tuple[str, ...],
    group_count: int,
    market: MarketState,
    initial_cash_minor: int,
    point_values: Mapping[str, float],
    lot_sizes: Mapping[str, float],
    allocator_factory: Callable[[str], WeightAllocator],
    allocation_inputs: Callable[[object, object], AllocationInput],
    rebalance_trigger_factory: Callable[[str], RebalanceTrigger],
    accounting_factory: Callable[[str], FillAccounting] | None = None,
) -> tuple[StrategyLane, ...]:
    """Build isolated group lanes that share only market data and factor signals."""

    if group_count <= 0 or group_count > len(instruments):
        raise ValueError("group_count must be within the instrument count")
    expected = set(instruments)
    if set(point_values) != expected or set(lot_sizes) != expected:
        raise ValueError("point values and lot sizes must cover all instruments")
    if accounting_factory is None:
        accounting_factory = lambda _: CashAccounting(point_values=point_values)
    sizer = EqualNotionalSizer(market, point_values, lot_sizes)
    lanes = []
    for group_number in range(1, group_count + 1):
        strategy_id = f"{strategy_prefix}:group-{group_number}"
        portfolio_id = f"{strategy_id}:portfolio"
        strategy = QuantileGroupStrategy(
            factor_alias=factor_alias,
            strategy_id=strategy_id,
            portfolio_id=portfolio_id,
            instruments=instruments,
            group_number=group_number,
            group_count=group_count,
            allocator=allocator_factory(strategy_id),
            allocation_inputs=allocation_inputs,
            rebalance_trigger=rebalance_trigger_factory(strategy_id),
        )
        ledger = Ledger(
            portfolio_id,
            instruments,
            initial_cash_minor,
            accounting_factory(portfolio_id),
        )
        lanes.append(StrategyLane(
            strategy,
            ledger,
            OrderManager(ledger, position_sizer=sizer),
        ))
    return tuple(lanes)
