"""Cash-pool target collection and margin-budget application."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, replace
from typing import Any

from tools.testers.backtest.modules.strategy_book import strategy_book_store_for
from tools.testers.backtest.modules.target import TargetStrategyModule, TargetWeightIntent
from tools.testers.backtest.policies.margin_budget import (
    MarginBudgetRequest,
    default_margin_budget_policy,
    validate_margin_budget_decision,
)

from .collection import cash_pool_equity, collect_target_items
from .models import TargetItem, require_one_pool_setting


def apply_target_margin_budget(state: Any, ctx: Any) -> None:
    from tools.testers.backtest.modules.margin_budget import MarginBudgetModule

    items, settings = collect_target_items(state, ctx)
    by_pool: dict[str, list[TargetItem]] = defaultdict(list)
    for item in items:
        by_pool[item.pool_id].append(item)

    scales: dict[str, float] = {}
    summaries: dict[str, dict[str, Any]] = {}
    for pool_id, pool_items in by_pool.items():
        enabled = {item.margin_enabled for item in pool_items}
        if len(enabled) > 1:
            raise ValueError(f"cash_pool {pool_id!r} cannot mix enabled and disabled margin targets")
        if enabled == {False}:
            continue
        pool_settings = require_one_pool_setting(pool_id, settings[pool_id])
        equity = cash_pool_equity(state, ctx, pool_items)
        request = MarginBudgetRequest(
            cash_pool_id=pool_id,
            effective_timestamp=ctx.timestamp,
            equity=equity,
            target_utilization=pool_settings.target,
            max_utilization=pool_settings.maximum,
            tolerance=pool_settings.tolerance,
            raw_gross_notional=sum(item.gross_notional for item in pool_items),
            raw_projected_margin=sum(item.projected_margin for item in pool_items),
        )
        policy = strategy_book_store_for(state).policies.margin_budget or default_margin_budget_policy
        decision = policy(request)
        validate_margin_budget_decision(request, decision)
        scales[pool_id] = float(decision.scale)
        summaries[pool_id] = asdict(decision)

    _apply_scales(state, ctx, items, scales)
    _publish(ctx, MarginBudgetModule, summaries)


def _apply_scales(state: Any, ctx: Any, items: list[TargetItem], scales: dict[str, float]) -> None:
    by_strategy: dict[Any, dict[Any, float]] = {}
    reasons: dict[Any, str] = {}
    for strategy in ctx.active_strategies:
        intent = ctx.get_for(TargetStrategyModule.trade_intent, strategy, None)
        if isinstance(intent, TargetWeightIntent):
            by_strategy[strategy] = dict(intent.weights)
            reasons[strategy] = intent.reason
    for item in items:
        if item.pool_id in scales:
            by_strategy[item.strategy][item.product] = item.weight * scales[item.pool_id]
    for strategy, weights in by_strategy.items():
        if not any(item.strategy == strategy and item.pool_id in scales for item in items):
            continue
        ctx.set_for(TargetStrategyModule.target_weights, strategy, weights)
        original = ctx.get_for(
            TargetStrategyModule.trade_intent, strategy,
        )
        ctx.set_for(
            TargetStrategyModule.trade_intent,
            strategy,
            replace(
                original,
                weights=weights,
                reason=f"{reasons[strategy]}|margin_budget",
            ),
        )
        state.target_store.record_target_trace(strategy, ctx.timestamp, weights)


def _publish(ctx: Any, module: Any, summaries: dict[str, dict[str, Any]]) -> None:
    ctx.set(module.margin_budget_summary, summaries)
    mapping = {
        module.cash_pool_equity: "equity",
        module.target_margin: "target_margin",
        module.projected_margin: "projected_margin",
        module.weighted_margin_ratio: "weighted_margin_ratio",
        module.target_scale: "scale",
        module.gross_leverage: "gross_leverage",
    }
    for ref, key in mapping.items():
        ctx.set(ref, {pool_id: values[key] for pool_id, values in summaries.items()})
