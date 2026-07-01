"""LongShortCompositionModule -- compose strategy legs into a new target.

Long-short is a peer strategy lane: it consumes source strategies' target
weights at the same decision timestamp and emits its own target weights.  In a
group test the source strategies usually happen to be quantile groups, but this
module deliberately only knows about strategy ids, not groupIndex/splitCount.
"""

from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.group_membership import GroupMembershipModule
from tools.testers.backtest.modules.target import TargetStrategyModule


_TARGET_WEIGHTS_REF: FieldRef[Any] = TargetStrategyModule.target_weights


class LongShortCompositionModule(TargetStrategyModule):
    key: ClassVar[str] = "long_short_strategy"
    label: ClassVar[str] = "Long-Short"
    order: ClassVar[int] = 85

    strategy_kind: ClassVar[FieldRef[str]] = FieldRef("strategy_kind")
    long_leg_strategy_ids: ClassVar[FieldRef[list[Any]]] = FieldRef("long_leg_strategy_ids")
    short_leg_strategy_ids: ClassVar[FieldRef[list[Any]]] = FieldRef("short_leg_strategy_ids")
    long_short_diagnostics: ClassVar[FieldRef[Any]] = FieldRef("long_short_diagnostics")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "strategy_kind": FieldDefinition(public=False, default="group"),
        "long_leg_strategy_ids": FieldDefinition(public=False, default=[]),
        "short_leg_strategy_ids": FieldDefinition(public=False, default=[]),
        "long_short_diagnostics": FieldDefinition(public=False, default={}),
    }

    compose_long_short_target: ClassVar[Flow] = Flow(
        "compose_long_short_target",
        inputs=(long_leg_strategy_ids, short_leg_strategy_ids),
        outputs=(_TARGET_WEIGHTS_REF, long_short_diagnostics),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL,
        order=15,
        after=(GroupMembershipModule.group_quantile_membership,),
        compute=lambda state, ctx: _compose_long_short_target(state, ctx),
        description="合成Long-Short目标",
    )

    flows: ClassVar[tuple[Flow, ...]] = (compose_long_short_target,)


def _compose_long_short_target(state, ctx) -> None:
    strategy_by_alias = _strategy_by_alias(state)
    for strategy in ctx.active_strategies:
        config = state.config_for(strategy)
        if str(config.get(LongShortCompositionModule.strategy_kind, "group")) != "long_short":
            continue
        long_legs = _resolve_leg_specs(
            config.get(LongShortCompositionModule.long_leg_strategy_ids, ()), strategy_by_alias)
        short_legs = _resolve_leg_specs(
            config.get(LongShortCompositionModule.short_leg_strategy_ids, ()), strategy_by_alias)
        diagnostics: dict[str, Any] = {
            "missing_long_legs": [leg["strategy_id"] for leg in long_legs if leg["strategy"] is None],
            "missing_short_legs": [leg["strategy_id"] for leg in short_legs if leg["strategy"] is None],
            "empty_long_leg_count": 0,
            "empty_short_leg_count": 0,
            "overlap_count": 0,
            "overlaps": [],
        }
        long_weights = _combined_leg_weights(ctx, long_legs, diagnostics, "long")
        short_weights = _combined_leg_weights(ctx, short_legs, diagnostics, "short")
        if not long_weights or not short_weights:
            ctx.set_for(_TARGET_WEIGHTS_REF, strategy, {})
            ctx.set_for(LongShortCompositionModule.long_short_diagnostics, strategy, diagnostics)
            continue

        overlap = set(long_weights) & set(short_weights)
        if overlap:
            diagnostics["overlap_count"] = len(overlap)
            diagnostics["overlaps"] = [str(product) for product in sorted(overlap, key=str)]
            for product in overlap:
                long_weights.pop(product, None)
                short_weights.pop(product, None)
        if not long_weights or not short_weights:
            ctx.set_for(_TARGET_WEIGHTS_REF, strategy, {})
            ctx.set_for(LongShortCompositionModule.long_short_diagnostics, strategy, diagnostics)
            continue

        target: dict[Any, float] = {}
        for product, weight in _normalize_abs(long_weights, gross=0.5).items():
            target[product] = target.get(product, 0.0) + weight
        for product, weight in _normalize_abs(short_weights, gross=0.5).items():
            target[product] = target.get(product, 0.0) - weight
        target = {product: weight for product, weight in target.items() if abs(weight) > 1e-12}
        ctx.set_for(_TARGET_WEIGHTS_REF, strategy, target)
        ctx.set_for(LongShortCompositionModule.long_short_diagnostics, strategy, diagnostics)
        _record_target_trace(state, strategy, ctx.timestamp, target)


def _strategy_by_alias(state) -> dict[str, Any]:
    return {str(strategy.alias): strategy for strategy in state.strategy_configs}


def _resolve_leg_specs(raw: Any, strategy_by_alias: dict[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    if not isinstance(raw, (list, tuple)):
        return specs
    for item in raw:
        if isinstance(item, dict):
            strategy_id = str(
                item.get("strategy_id")
                or item.get("group_id")
                or item.get("id")
                or ""
            )
            weight = _safe_float(item.get("weight"), 1.0)
        else:
            strategy_id = str(item or "")
            weight = 1.0
        if not strategy_id:
            continue
        specs.append({
            "strategy_id": strategy_id,
            "strategy": strategy_by_alias.get(strategy_id),
            "weight": weight,
        })
    return specs


def _combined_leg_weights(ctx, legs: list[dict[str, Any]], diagnostics: dict[str, Any], side: str) -> dict[Any, float]:
    combined: dict[Any, float] = {}
    for leg in legs:
        source = leg.get("strategy")
        if source is None:
            continue
        weights = ctx.get_for(_TARGET_WEIGHTS_REF, source, {})
        if not weights:
            diagnostics[f"empty_{side}_leg_count"] += 1
            continue
        leg_weight = float(leg.get("weight") or 1.0)
        for product, weight in weights.items():
            combined[product] = combined.get(product, 0.0) + abs(float(weight)) * leg_weight
    return combined


def _normalize_abs(weights: dict[Any, float], *, gross: float) -> dict[Any, float]:
    total = sum(abs(float(value)) for value in weights.values())
    if total <= 0:
        return {}
    return {product: gross * abs(float(value)) / total for product, value in weights.items()}


def _record_target_trace(state, strategy, timestamp, weights: dict[Any, float]) -> None:
    if timestamp is None:
        return
    state.target_store.record_target_trace(strategy, timestamp, weights)


def _safe_float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default
