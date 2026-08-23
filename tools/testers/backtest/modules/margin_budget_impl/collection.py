"""Collect causal target and margin inputs by cash pool."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    contract_multiplier_from_fields,
    historical_fields_for_product,
)
from tools.testers.backtest.modules.margin import _resolve_margin_mode, product_uses_margin_accounting
from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger, ledger_for_strategy_product
from tools.testers.backtest.modules.target import TargetStrategyModule, TargetWeightIntent

from .models import PoolSettings, TargetItem, settings_for_pool


def collect_target_items(
    state: Any,
    ctx: Any,
) -> tuple[list[TargetItem], dict[str, list[PoolSettings]]]:
    from tools.testers.backtest.modules.ledger_module import _resolved_margin_ratio_for_position_after_fill
    from tools.testers.backtest.modules.margin_budget import MarginBudgetModule

    prices = ctx.get(MarketDataModule.current_prices, {}) or {}
    items: list[TargetItem] = []
    settings: dict[str, list[PoolSettings]] = defaultdict(list)
    for strategy in ctx.active_strategies:
        intent = ctx.get_for(TargetStrategyModule.trade_intent, strategy, None)
        if not isinstance(intent, TargetWeightIntent):
            continue
        config = state.config_for(strategy)
        equity = float(ctx.get_for(LedgerModule.equity, strategy))
        historical = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        ) or {}
        seen_pools: set[str] = set()
        for product, raw_weight in intent.weights.items():
            weight = float(raw_weight)
            if abs(weight) <= 1e-12:
                continue
            ledger = ledger_for_strategy_product(state, strategy, product)
            pool_id = cash_pool_id_for_ledger(state, ledger)
            ledger_config = state.ledger_config_for(ledger)
            enabled = _resolve_margin_mode(config, ledger_config) not in {"none", "zero"}
            fields = historical_fields_for_product(historical, product)
            price = float(prices[product])
            multiplier = contract_multiplier_from_fields(
                historical, product, state=state, timestamp=ctx.timestamp,
            )
            ratio = 1.0
            if enabled and product_uses_margin_accounting(fields, ledger_config):
                ratio = _resolved_margin_ratio_for_position_after_fill(
                    config, fields, weight, price, multiplier, ledger_config,
                )
            items.append(TargetItem(
                strategy=strategy, product=product, ledger=ledger, pool_id=pool_id,
                equity=equity, weight=weight, margin_ratio=float(ratio), margin_enabled=enabled,
            ))
            if pool_id not in seen_pools:
                settings[pool_id].append(settings_for_pool(
                    state, pool_id, config, MarginBudgetModule,
                ))
                seen_pools.add(pool_id)
    return items, settings


def cash_pool_equity(state: Any, ctx: Any, items: list[TargetItem]) -> float:
    from tools.testers.backtest.modules.ledger_impl.valuation import cash_pool_equity as value_pool

    return value_pool(state, ctx, items[0].ledger)
