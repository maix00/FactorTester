"""Cash-pool hard margin-utilization enforcement."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from tools.testers.backtest.modules.cash_pool import cash_pool_money
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.margin import _resolve_margin_mode
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

from .models import PoolSettings, require_one_pool_setting, settings_for_pool
from .execution_output import apply_execution_scale, publish_execution_summary
from .execution_projection import find_scale, order_components, pool_equity
from .simulation import margin_reserved, project_components


def enforce_execution_margin_limit(state: Any, ctx: Any) -> None:
    from tools.testers.backtest.engines.native.order import OrderStatus
    from tools.testers.backtest.modules.margin_budget import MarginBudgetModule

    observer = getattr(state, "margin_execution_observer", None)
    groups: dict[str, list[tuple[Any, Any, Any, dict]]] = defaultdict(list)
    settings: dict[str, list[PoolSettings]] = defaultdict(list)
    for strategy in ctx.active_strategies:
        historical = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        ) or {}
        seen: set[str] = set()
        for order in ctx.payloads_for(strategy):
            if order.status == OrderStatus.CANCELLED or order.get("reject_reason"):
                continue
            ledger = state.ledger_for(order)
            if _resolve_margin_mode(state.config_for(strategy), state.ledger_config_for(ledger)) in {"none", "zero"}:
                continue
            pool = cash_pool_id_for_ledger(state, ledger)
            groups[pool].append((strategy, order, ledger, historical))
            if pool not in seen:
                config = state.config_for(strategy)
                settings[pool].append(settings_for_pool(
                    state, pool, config, MarginBudgetModule,
                ))
                seen.add(pool)

    summaries = {}
    for pool, entries in groups.items():
        observation = observer.begin_pool(pool, len(entries)) if observer is not None else None
        pool_settings = require_one_pool_setting(pool, settings[pool])
        positions = _observed_stage(
            observer,
            observation,
            "clone_positions",
            _clone_pool_positions,
            entries,
        )
        components = _observed_stage(
            observer, observation, "order_components", order_components,
            entries, positions,
        )
        first_ledger = entries[0][2]
        cash = _observed_stage(
            observer, observation, "cash_lookup", cash_pool_money,
            state, first_ledger, timestamp=ctx.timestamp,
        )
        if cash is None:
            raise KeyError(f"cash_pool {pool!r} has no cash")
        initial_margin = _observed_stage(
            observer, observation, "initial_margin", margin_reserved,
            state, ctx, components, positions,
        )
        initial_equity = _observed_stage(
            observer, observation, "pool_equity", pool_equity,
            state, ctx, entries, float(cash.to_major()),
        )
        reduced = _projected_stage(
            observer, observation, "project_reducing",
            state, ctx, components, positions, cash, initial_equity, initial_margin,
            include_reducing=True, increasing_scale=0.0,
        )
        full = _projected_stage(
            observer, observation, "project_full",
            state, ctx, components, reduced.positions, reduced.cash, reduced.equity, reduced.margin,
            include_reducing=False, increasing_scale=1.0,
        )
        scale = 1.0
        over_limit = full.utilization > pool_settings.maximum + 1e-12
        if full.utilization <= pool_settings.maximum + 1e-12:
            continuous = final = full
        else:
            scale = _observed_stage(
                observer, observation, "find_scale", find_scale,
                state, ctx, components, reduced, pool_settings.maximum,
                observer, observation,
            )
            continuous = _projected_stage(
                observer, observation, "project_continuous",
                state, ctx, components, reduced.positions, reduced.cash,
                reduced.equity, reduced.margin, include_reducing=False, increasing_scale=scale,
            )
            before_quantities = {id(component.order): float(component.order.quantity) for component in components}
            _observed_stage(
                observer, observation, "apply_execution_scale", apply_execution_scale,
                state, ctx, components, scale, pool_settings.maximum,
            )
            scaled_orders = sum(
                abs(float(component.order.quantity) - before_quantities[id(component.order)]) > 1e-12
                for component in components
            )
            actual_components = _observed_stage(
                observer, observation, "order_components_after_scale", order_components,
                entries, positions,
            )
            final = _projected_stage(
                observer, observation, "project_final",
                state, ctx, actual_components, reduced.positions, reduced.cash,
                reduced.equity, reduced.margin,
                include_reducing=False, increasing_scale=1.0,
            )
        if not over_limit:
            scaled_orders = 0
        if observer is not None:
            observer.end_pool(
                observation,
                over_limit=over_limit,
                scaled_orders=scaled_orders,
                scale=scale,
                full_utilization=full.utilization,
                final_utilization=final.utilization,
                maximum=pool_settings.maximum,
            )
        summaries[pool] = {
            "cash_pool_id": pool, "equity": final.equity,
            "projected_margin": final.margin,
            "projected_utilization": final.utilization,
            "max_utilization": pool_settings.maximum,
            "hard_limit_headroom": pool_settings.maximum - final.utilization,
            "gross_leverage": final.gross_notional / final.equity if final.equity > 0 else float("inf"),
            "execution_scale": scale,
            "rounding_error": final.utilization - continuous.utilization,
        }
    publish_execution_summary(ctx, summaries)


def _clone_pool_positions(entries):
    from tools.testers.backtest.modules.cash_rescale import _clone_positions_for_cash_check

    return {
        id(ledger): _clone_positions_for_cash_check(
            _active_positions(ledger.get(LedgerModule.positions, {}) or {})
        )
        for _strategy, _order, ledger, _historical in entries
    }


def _active_positions(positions: dict) -> dict:
    """Drop zero-position tombstones from an execution projection.

    Contract rollover leaves historical instruments in the ledger mapping.
    They remain useful for inspection, but they cannot change projected cash,
    margin, or gross notional once both quantity and reserved margin are zero.
    Avoid copying them for every hard-limit projection while retaining any
    record that still carries an economic balance.
    """
    active = {}
    for product, entry in positions.items():
        quantity = abs(float(getattr(entry, "quantity", 0.0) or 0.0))
        reserved = getattr(entry, "margin_reserved", None)
        reserved_major = (
            abs(float(reserved.to_major())) if reserved is not None else 0.0
        )
        if quantity > 1e-12 or reserved_major > 1e-12:
            active[product] = entry
    return active


def _observed_stage(observer, token, name, operation, *args, **kwargs):
    if observer is None:
        return operation(*args, **kwargs)
    stage_token = observer.begin_stage(token, name)
    try:
        return operation(*args, **kwargs)
    finally:
        observer.end_stage(token, name, stage_token)


def _projected_stage(observer, token, name, state, ctx, components, positions, cash, equity, margin, **kwargs):
    result = _observed_stage(
        observer, token, name, project_components,
        state, ctx, components, positions, cash, equity, margin, **kwargs,
    )
    if observer is not None:
        observer.record_projection(token)
    return result
