"""Cash-pool hard margin-utilization enforcement."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from tools.testers.backtest.modules.cash_pool import cash_for_ledger
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
    from tools.testers.backtest.modules.cash_rescale import _clone_positions_for_cash_check
    from tools.testers.backtest.modules.margin_budget import MarginBudgetModule

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
        pool_settings = require_one_pool_setting(pool, settings[pool])
        positions = {
            id(ledger): _clone_positions_for_cash_check(ledger.get(LedgerModule.positions, {}))
            for _strategy, _order, ledger, _historical in entries
        }
        components = order_components(entries, positions)
        first_ledger = entries[0][2]
        cash = cash_for_ledger(state, first_ledger)
        if cash is None:
            raise KeyError(f"cash_pool {pool!r} has no cash")
        initial_margin = margin_reserved(positions)
        initial_equity = pool_equity(state, ctx, entries, float(cash.to_major()))
        reduced = project_components(
            state, ctx, components, positions, cash, initial_equity, initial_margin,
            include_reducing=True, increasing_scale=0.0,
        )
        full = project_components(
            state, ctx, components, reduced.positions, reduced.cash, reduced.equity, reduced.margin,
            include_reducing=False, increasing_scale=1.0,
        )
        scale = 1.0
        continuous = full
        if full.utilization > pool_settings.maximum + 1e-12:
            scale = find_scale(state, ctx, components, reduced, pool_settings.maximum)
            continuous = project_components(
                state, ctx, components, reduced.positions, reduced.cash,
                reduced.equity, reduced.margin, include_reducing=False, increasing_scale=scale,
            )
            apply_execution_scale(state, ctx, components, scale, pool_settings.maximum)
        actual_components = order_components(entries, positions)
        final = project_components(
            state, ctx, actual_components, reduced.positions, reduced.cash, reduced.equity, reduced.margin,
            include_reducing=False, increasing_scale=1.0,
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
