"""Causal SIGNAL-stage incremental cash and margin estimate."""

from __future__ import annotations

from collections import defaultdict
from copy import copy
from typing import Any

from tools.testers.backtest.modules.cash_pool import cash_for_ledger
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_construct import OrderConstructModule
from tools.testers.backtest.modules.strategy_book import available_cash_for_ledger, cash_pool_id_for_ledger

from .fees import estimate_signal_fee
from .batch import add_cash, apply_scale, components


def constrain_signal_orders(state: Any, ctx: Any) -> None:
    from tools.testers.backtest.modules.cash_rescale import (
        _clone_positions_for_cash_check,
        _estimated_execution_cash_delta,
        _round_execution_scaled_quantity,
    )

    prices = ctx.get(MarketDataModule.current_prices, {}) or {}
    groups: dict[str, list[tuple[Any, Any, Any, dict]]] = defaultdict(list)
    for strategy in ctx.active_strategies:
        historical = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        ) or {}
        for order in ctx.get_for(OrderConstructModule.orders, strategy, []):
            ledger = state.ledger_for(order)
            groups[cash_pool_id_for_ledger(state, ledger)].append((strategy, order, ledger, historical))

    for pool_id, entries in groups.items():
        first_ledger = entries[0][2]
        cash = cash_for_ledger(state, first_ledger)
        if cash is None:
            raise RuntimeError(f"cash_pool {pool_id!r} has no cash")
        available = available_cash_for_ledger(
            state, first_ledger, float(cash.to_major()), reason="signal_order",
        )
        positions = {
            id(ledger): _clone_positions_for_cash_check(ledger.get(LedgerModule.positions, {}))
            for _strategy, _order, ledger, _historical in entries
        }
        parts = components(entries, positions)
        simulated_cash = cash
        release = 0.0
        for entry, reducing, _increasing in parts:
            if abs(reducing) <= 1e-12:
                continue
            delta = _cash_delta(state, ctx, entry, reducing, positions, simulated_cash, prices)
            release += delta
            simulated_cash = add_cash(simulated_cash, delta)
        requirements: list[tuple[tuple[Any, Any, Any, dict], float, float]] = []
        for entry, reducing, increasing in parts:
            if abs(increasing) <= 1e-12:
                continue
            delta = _cash_delta(state, ctx, entry, increasing, positions, simulated_cash, prices)
            simulated_cash = add_cash(simulated_cash, delta)
            if delta < -1e-12:
                requirements.append((entry, reducing, -delta))
            elif delta > 1e-12:
                release += delta
        required = sum(amount for _entry, _reducing, amount in requirements)
        capacity = max(available + release, 0.0)
        if required <= capacity + 1e-9:
            continue
        scale = 0.0 if required <= 0 else capacity / required
        constrained = {id(entry[1]) for entry, _reducing, _amount in requirements}
        apply_scale(
            state, ctx, parts, constrained, scale, available, required,
            step="cash_rescale", label="按增量保证金约束调整订单",
            recalculate_fee=False,
        )


def _cash_delta(state, ctx, entry, quantity, positions, cash, prices) -> float:
    from tools.testers.backtest.modules.cash_rescale import _estimated_execution_cash_delta

    strategy, order, ledger, historical = entry
    candidate = copy(order)
    candidate.quantity = quantity
    price = float(prices[order.instrument])
    candidate.set("effective_price", price)
    candidate.set("fee_cost", estimate_signal_fee(
        state, ctx, strategy, ledger, candidate, historical, positions[id(ledger)], price,
    ))
    return _estimated_execution_cash_delta(
        cash, positions[id(ledger)], state.config_for(strategy), candidate,
        historical, state.ledger_config_for(ledger), prices,
    )
