"""Authoritative ORDER-stage incremental cash and margin constraint."""

from __future__ import annotations

from collections import defaultdict
from copy import copy
from typing import Any

from tools.testers.backtest.modules.cash_pool import (
    account_cash_or_zero,
    cash_amount_to_pool_base,
    cash_pool_money,
)
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.market_data import historical_fields_for_product
from tools.testers.backtest.modules.strategy_book import available_cash_for_ledger, cash_pool_id_for_ledger

from .batch import add_cash, apply_scale, components


def constrain_execution_orders(state: Any, ctx: Any) -> None:
    from tools.testers.backtest.engines.native.order import OrderStatus
    from tools.testers.backtest.modules.cash_rescale import (
        _clone_positions_for_cash_check,
        _execution_cash_required_upper_bound,
    )

    prices = ctx.get(MarketDataModule.current_prices, {}) or {}
    groups: dict[str, list[tuple[Any, Any, Any, dict]]] = defaultdict(list)
    for strategy in ctx.active_strategies:
        historical = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        ) or {}
        for order in ctx.payloads_for(strategy):
            if order.status == OrderStatus.CANCELLED or order.get("reject_reason"):
                continue
            ledger = state.ledger_for(order)
            groups[cash_pool_id_for_ledger(state, ledger)].append((strategy, order, ledger, historical))

    for pool_id, entries in groups.items():
        strategy_configs = {
            strategy: state.config_for(strategy)
            for strategy, _order, _ledger, _historical in entries
        }
        ledger_configs: dict[int, tuple[Any, Any]] = {}
        for _strategy, _order, ledger, _historical in entries:
            ledger_key = id(ledger)
            if ledger_key not in ledger_configs:
                ledger_configs[ledger_key] = (ledger, state.ledger_config_for(ledger))
        first_ledger = entries[0][2]
        cash = cash_pool_money(
            state, first_ledger, timestamp=ctx.timestamp,
            include_conversion_cost=True,
        )
        available = available_cash_for_ledger(
            state, first_ledger, float(cash.to_major()), reason="execution_order",
        )
        upper_bound = sum(
            cash_amount_to_pool_base(
                state, ledger,
                _execution_cash_required_upper_bound(
                state, ctx, ledger, [(strategy, [order], historical)],
                strategy_config=strategy_configs[strategy],
                ledger_config=ledger_configs[id(ledger)][1],
                ),
                timestamp=ctx.timestamp, include_conversion_cost=True,
            )
            for strategy, order, ledger, historical in entries
        )
        if upper_bound <= max(available, 0.0) + 1e-9:
            continue
        # All legs sharing a ledger must see one sequential simulation state.
        # The previous comprehension cloned the same starting positions once
        # per order and retained only the last clone, adding cost without
        # changing the simulated state.
        positions = {}
        for _strategy, _order, ledger, _historical in entries:
            ledger_key = id(ledger)
            if ledger_key not in positions:
                positions[ledger_key] = _clone_positions_for_cash_check(
                    ledger.get(LedgerModule.positions, {})
                )
        parts = components(entries, positions)
        simulated_cash = cash
        release = 0.0
        for entry, reducing, _increasing in parts:
            if abs(reducing) <= 1e-12:
                continue
            delta = _cash_delta(
                state, ctx, entry, reducing, positions, simulated_cash, prices,
                strategy_config=strategy_configs[entry[0]],
                ledger_config=ledger_configs[id(entry[2])][1],
            )
            release += delta
            simulated_cash = add_cash(simulated_cash, delta)
        required_parts = []
        for entry, reducing, increasing in parts:
            if abs(increasing) <= 1e-12:
                continue
            delta = _cash_delta(
                state, ctx, entry, increasing, positions, simulated_cash, prices,
                strategy_config=strategy_configs[entry[0]],
                ledger_config=ledger_configs[id(entry[2])][1],
            )
            simulated_cash = add_cash(simulated_cash, delta)
            if delta < -1e-12:
                required_parts.append((entry, reducing, -delta))
            elif delta > 1e-12:
                release += delta
        required = sum(item[2] for item in required_parts)
        capacity = max(available + release, 0.0)
        if required <= capacity + 1e-9:
            continue
        scale = 0.0 if required <= 0 else capacity / required
        constrained = {id(entry[1]) for entry, _reducing, _amount in required_parts}
        apply_scale(
            state, ctx, parts, constrained, scale, capacity, required,
            step="execution_cash_constraint", label="成交增量保证金约束",
            recalculate_fee=True,
        )


def _cash_delta(
    state, ctx, entry, quantity, positions, cash, prices, *,
    strategy_config=None, ledger_config=None,
) -> float:
    from tools.testers.backtest.modules.cash_rescale import _estimated_execution_cash_delta

    strategy, order, ledger, historical = entry
    if strategy_config is None:
        strategy_config = state.config_for(strategy)
    if ledger_config is None:
        ledger_config = state.ledger_config_for(ledger)
    candidate = copy(order)
    candidate.quantity = quantity
    product_fields = historical_fields_for_product(historical, order.instrument)
    ledger_cash = account_cash_or_zero(state, ledger)
    delta = _estimated_execution_cash_delta(
        ledger_cash, positions[id(ledger)], strategy_config, candidate,
        historical, ledger_config, prices,
        product_fields=product_fields,
    )
    return cash_amount_to_pool_base(
        state, ledger, delta, timestamp=ctx.timestamp,
        include_conversion_cost=True,
    )
