from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    is_product_tradable,
)
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.target import (
    PairedTargetWeightIntent,
    TargetStrategyModule,
)
from tools.testers.backtest.modules.term_carry_validation import (
    validate_term_carry_config,
)


@dataclass
class TermCarryStrategyStore:
    directions: dict[tuple[Any, Any], int] = field(default_factory=dict)
    targets: dict[tuple[Any, Any], dict[Any, float]] = field(default_factory=dict)
    contract_cache: dict[tuple[Any, Any, int], tuple[Any, ...]] = field(default_factory=dict)


def term_carry_strategy_store_for(state) -> TermCarryStrategyStore:
    store = getattr(state, "term_carry_strategy_store", None)
    if store is None:
        store = TermCarryStrategyStore()
        setattr(state, "term_carry_strategy_store", store)
    return store


def build_term_carry_targets(state, ctx, module) -> None:
    for strategy in ctx.active_strategies:
        config = state.config_for(strategy)
        if config.get(TargetStrategyModule.strategy_kind) != "term_carry":
            continue
        signals = ctx.get_for(module._signal_value_ref, strategy, {}) or {}
        products = ctx.get_for(ProductSelectionModule.products, strategy, ())
        targets, diagnostics = _strategy_targets(
            state, ctx, module, strategy, config, signals, products,
        )
        intent_id = f"term-carry:{strategy.alias}:{ctx.timestamp}"
        intent = PairedTargetWeightIntent(
            targets,
            reason="term_carry",
            parent_intent_id=intent_id,
        )
        ctx.set_for(TargetStrategyModule.target_weights, strategy, targets)
        ctx.set_for(TargetStrategyModule.trade_intent, strategy, intent)
        ctx.set_for(module.diagnostics, strategy, diagnostics)


def _strategy_targets(state, ctx, module, strategy, config, signals, products):
    products = tuple(products)
    store = term_carry_strategy_store_for(state)
    prices = ctx.get(MarketDataModule.current_prices, {}) or {}
    tradable = ctx.get(MarketDataModule.current_tradable_status, None)
    entry = abs(float(config.get(module.entry_threshold, 0.0)))
    exit_at = abs(float(config.get(module.exit_threshold, 0.0)))
    near_rank = int(config.get(module.near_rank, 0))
    far_rank = int(config.get(module.far_rank, 1))
    gross = float(config.get(module.gross_weight, 1.0))
    validate_term_carry_config(
        near_rank=near_rank,
        far_rank=far_rank,
        entry=entry,
        exit_at=exit_at,
        gross=gross,
    )
    resolved: list[tuple[Any, int, tuple[Any, Any]]] = []
    preserved: dict[Any, float] = {}
    diagnostics = {"blocked": {}, "directions": {}, "contracts": {}}
    for product in products:
        signal = _finite_signal(signals.get(product))
        key = (strategy, product)
        previous = store.directions.get(key, 0)
        direction = _next_direction(previous, signal, entry, exit_at)
        contracts = _ranked_contracts(
            state, product, ctx.timestamp, far_rank + 1,
        )
        if len(contracts) <= far_rank:
            diagnostics["blocked"][str(product)] = "missing_contract_leg"
            direction = previous
            preserved.update(store.targets.get(key, {}))
        else:
            pair = (contracts[near_rank], contracts[far_rank])
            if not all(
                leg in prices and is_product_tradable(tradable, leg, prices)
                for leg in pair
            ):
                diagnostics["blocked"][str(product)] = "missing_leg_market"
                direction = previous
            resolved.append((product, direction, pair))
            diagnostics["contracts"][str(product)] = [str(leg) for leg in pair]
        store.directions[key] = direction
        diagnostics["directions"][str(product)] = direction
    product_count = len(products)
    leg_weight = gross / (2 * product_count) if product_count else 0.0
    targets: dict[Any, float] = dict(preserved)
    for product, direction, pair in resolved:
        pair_target = {} if direction == 0 else {
            pair[0]: direction * leg_weight,
            pair[1]: -direction * leg_weight,
        }
        store.targets[(strategy, product)] = pair_target
        targets.update(pair_target)
    return targets, diagnostics


def _next_direction(previous: int, signal, entry: float, exit_at: float) -> int:
    if signal is None:
        return previous
    if abs(signal) <= exit_at:
        return 0
    if signal >= entry:
        return 1
    if signal <= -entry:
        return -1
    return previous


def _finite_signal(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _ranked_contracts(state, product, timestamp, depth: int) -> tuple[Any, ...]:
    store = term_carry_strategy_store_for(state)
    resolver = state.market_data_store.trading_day_resolver
    day = (
        resolver.resolve_trading_day(timestamp, instrument=str(product))
        if resolver is not None
        else timestamp.normalize()
    )
    key = (product, day, depth)
    if key not in store.contract_cache:
        getter = getattr(product, "get_term_structure_contracts", None)
        store.contract_cache[key] = tuple(
            getter(day, depth=depth) if callable(getter) else ()
        )
    return store.contract_cache[key]
