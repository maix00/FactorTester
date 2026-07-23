"""ThresholdSignalModule -- non-group signal-to-target implementation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, cast

import pandas as pd

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.group_membership import (
    GroupMembershipModule,
    _allocate_weights,
    _record_target_trace,
    _tradable_signal_values,
)
from tools.testers.backtest.modules.market_data import MarketDataModule, current_prices_at
from tools.testers.backtest.modules.strategy_book import StrategyIntentPolicy
from tools.testers.backtest.modules.target import (
    TargetStrategyModule,
    _generate_strategy_intents,
    register_strategy_intent_policy,
    target_weight_intent,
)
from tools.testers.backtest.modules.time_index_lookup import row_at_index_key, signal_event_times


class ThresholdSignalModule(TargetStrategyModule):
    key: ClassVar[str] = "threshold_signal"
    label: ClassVar[str] = "阈值信号"

    threshold_mode: ClassVar[FieldRef[str]] = FieldRef("threshold_mode")
    entry_threshold: ClassVar[FieldRef[float]] = FieldRef("entry_threshold")
    exit_threshold: ClassVar[FieldRef[float]] = FieldRef("exit_threshold")
    quantile_entry: ClassVar[FieldRef[float]] = FieldRef("quantile_entry")
    quantile_exit: ClassVar[FieldRef[float]] = FieldRef("quantile_exit")
    side_mode: ClassVar[FieldRef[str]] = FieldRef("side_mode")
    target_weights: ClassVar[FieldRef[Any]] = TargetStrategyModule.target_weights

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "threshold_mode": FieldDefinition(
            public=True,
            label="阈值模式",
            default="absolute",
            control_template="select",
            tab="group_strategy",
            options=(("absolute", "绝对阈值"), ("cross_section_quantile", "截面分位")),
            chip_template="阈值模式: {value}",
            tab_label="分组数量",
            tab_order=90,
            visible_when={"strategy_intent_mode": ("threshold",)},
        ),
        "entry_threshold": FieldDefinition(
            public=True,
            label="入场阈值",
            default=0.0,
            control_template="number",
            tab="group_strategy",
            chip_template="入场阈值: {value}",
            tab_label="分组数量",
            tab_order=90,
            visible_when={"strategy_intent_mode": ("threshold",), "threshold_mode": ("absolute",)},
        ),
        "exit_threshold": FieldDefinition(
            public=True,
            label="退出阈值",
            default=0.0,
            control_template="number",
            tab="group_strategy",
            chip_template="退出阈值: {value}",
            tab_label="分组数量",
            tab_order=90,
            visible_when={"strategy_intent_mode": ("threshold",), "threshold_mode": ("absolute",)},
        ),
        "quantile_entry": FieldDefinition(
            public=True,
            label="入场分位",
            default=0.8,
            control_template="number",
            tab="group_strategy",
            minimum=0.0,
            maximum=1.0,
            step=0.01,
            chip_template="入场分位: {value}",
            tab_label="分组数量",
            tab_order=90,
            visible_when={"strategy_intent_mode": ("threshold",), "threshold_mode": ("cross_section_quantile",)},
        ),
        "quantile_exit": FieldDefinition(
            public=True,
            label="退出分位",
            default=0.6,
            control_template="number",
            tab="group_strategy",
            minimum=0.0,
            maximum=1.0,
            step=0.01,
            chip_template="退出分位: {value}",
            tab_label="分组数量",
            tab_order=90,
            visible_when={"strategy_intent_mode": ("threshold",), "threshold_mode": ("cross_section_quantile",)},
        ),
        "side_mode": FieldDefinition(
            public=True,
            label="方向",
            default="long_only",
            control_template="select",
            tab="group_strategy",
            options=(
                ("long_only", "只做多"),
                ("short_only", "只做空"),
                ("long_short_spread", "多空价差"),
            ),
            chip_template="方向: {value}",
            tab_label="分组数量",
            tab_order=90,
            visible_when={"strategy_intent_mode": ("threshold",)},
        ),
    }

    threshold_signal_target: ClassVar[Flow] = Flow(
        "threshold_signal_target",
        inputs=(
            TargetStrategyModule.strategy_kind,
            FactorSignalModule.signal_value,
            MarketDataModule.current_prices,
            MarketDataModule.current_tradable_status,
            threshold_mode,
            entry_threshold,
            exit_threshold,
            quantile_entry,
            quantile_exit,
            side_mode,
            GroupMembershipModule.allocation_policy,
            GroupMembershipModule.volatility_lookback,
            GroupMembershipModule.volatility_warmup,
        ),
        outputs=(target_weights, TargetStrategyModule.trade_intent),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL,
        description="计算阈值信号目标",
        order=10,
        compute=lambda state, ctx: _generate_strategy_intents(state, ctx, expected_kind="threshold"),
    )

    flows: ClassVar[tuple[Flow, ...]] = (threshold_signal_target,)


class ThresholdSignalIntentPolicy(StrategyIntentPolicy):
    def generate_strategy_intents(self, state: object, ctx: object, strategies: Sequence[object]) -> None:
        _threshold_signal_target(state, ctx, strategies)

    def precompute_strategy_intents(self, state: object, ctx: object, strategies: Sequence[object]) -> None:
        _precompute_threshold_target_intents(state, strategies)


def _threshold_signal_target(state, ctx, strategies: Sequence[object] | None = None) -> None:
    active_strategies = strategies if strategies is not None else ctx.active_strategies
    for strategy in active_strategies:
        config = state.config_for(strategy)
        if str(config.get(TargetStrategyModule.strategy_kind, "group") or "group") != "threshold":
            continue
        if _apply_precomputed_threshold_intent(state, ctx, strategy):
            continue
        signal_value = _rankable_signal_values(
            ctx.get_for(FactorSignalModule.signal_value, strategy, {}),
            ctx.get(MarketDataModule.current_prices),
            ctx.get(MarketDataModule.current_tradable_status, None),
        )
        weights, selection = _compute_threshold_target_weights(state, ctx, strategy, signal_value)
        ctx.set_for(ThresholdSignalModule.target_weights, strategy, weights)
        ctx.set_for(TargetStrategyModule.trade_intent, strategy, target_weight_intent(
            weights, reason="threshold_signal"))
        _store_threshold_selection(state, strategy, selection, weights)
        _record_target_trace(state, strategy, ctx.timestamp, weights)


def _apply_precomputed_threshold_intent(state, ctx, strategy) -> bool:
    if ctx.timestamp is None:
        return False
    table = state.target_store.precomputed_target_intents.get(strategy)
    if table is None:
        return False
    key = _target_intent_event_key(ctx, strategy)
    intent = table.get(key) or table.get(pd.Timestamp(ctx.timestamp))
    if intent is None:
        ctx.set_for(ThresholdSignalModule.target_weights, strategy, {})
        ctx.set_for(TargetStrategyModule.trade_intent, strategy, target_weight_intent(
            {}, reason="precomputed_threshold_missing"))
        return True
    ctx.set_for(ThresholdSignalModule.target_weights, strategy, intent.weights)
    ctx.set_for(TargetStrategyModule.trade_intent, strategy, intent)
    _record_target_trace(state, strategy, ctx.timestamp, intent.weights)
    return True


def _target_intent_event_key(ctx, strategy) -> Any:
    try:
        draft = ctx.draft_for(strategy)
    except Exception:
        return pd.Timestamp(ctx.timestamp)
    return draft.index_key if draft.index_key is not None else pd.Timestamp(ctx.timestamp)


class _ThresholdPrecomputeContext:
    def __init__(self, *, timestamp: pd.Timestamp, prices: dict) -> None:
        self.timestamp = timestamp
        self._values = {
            MarketDataModule.current_prices: prices,
            MarketDataModule.current_tradable_status: None,
        }

    def get(self, ref, default=None):
        return self._values.get(ref, default)

    def get_for(self, ref, strategy, default=None):
        return default


def _precompute_threshold_target_intents(state: object, strategies: Sequence[object]) -> None:
    signal_store = state.factor_signal_store
    established: dict[Any, dict[Any, float]] = {}
    selections: dict[Any, dict[str, frozenset]] = {}
    by_event: dict[Any, list[tuple[Any, Any, dict]]] = {}
    for strategy in strategies:
        table = signal_store.precomputed_table_for(strategy)
        if table is None:
            continue
        state.target_store.precomputed_target_intents.setdefault(strategy, {})
        for event_time in signal_event_times(table):
            by_event.setdefault(event_time.index_key, []).append(
                (strategy, event_time, _signal_values_from_table(table, event_time.index_key))
            )

    ordered = sorted(by_event.items(), key=lambda item: cast(pd.Timestamp, item[1][0][1].timestamp))
    for _event_key, items in ordered:
        timestamp = cast(pd.Timestamp, items[0][1].timestamp)
        prices = current_prices_at(state, timestamp)
        pre_ctx = _ThresholdPrecomputeContext(timestamp=timestamp, prices=prices)
        for strategy, event_time, signal_value in items:
            weights, selection = _compute_threshold_target_weights(
                state,
                pre_ctx,
                strategy,
                _rankable_signal_values(signal_value, prices, None),
                previous_selection=selections.get(strategy),
                previous_weights=established.get(strategy),
            )
            selections[strategy] = selection
            established[strategy] = weights
            intent = target_weight_intent(weights, reason="precomputed_threshold_signal")
            table = state.target_store.precomputed_target_intents[strategy]
            table[event_time.index_key] = intent
            table[event_time.timestamp] = intent


def _signal_values_from_table(table: pd.DataFrame, index_key: Any) -> dict:
    try:
        row = row_at_index_key(table, index_key) if index_key is not None else table.iloc[-1]
    except KeyError:
        return {}
    return {
        product: float(cast(Any, row[product]))
        for product in table.columns
        if not pd.isna(row[product])
    }


def _compute_threshold_target_weights(
    state,
    ctx,
    strategy,
    signal_value: dict,
    *,
    previous_selection: dict[str, frozenset] | None = None,
    previous_weights: dict[Any, float] | None = None,
) -> tuple[dict[Any, float], dict[str, frozenset]]:
    previous_selection = previous_selection if previous_selection is not None else _last_threshold_selection(state, strategy)
    config = state.config_for(strategy)
    mode = str(config.get(ThresholdSignalModule.threshold_mode, "absolute") or "absolute")
    side_mode = str(config.get(ThresholdSignalModule.side_mode, "long_only") or "long_only")
    if not signal_value:
        return {}, {"long": frozenset(), "short": frozenset()}

    long_members: frozenset = frozenset()
    short_members: frozenset = frozenset()
    if side_mode in {"long_only", "long_short_spread"}:
        long_members = _select_threshold_side(
            signal_value,
            mode=mode,
            positive_side=True,
            entry=float(config.get(ThresholdSignalModule.entry_threshold, 0.0) or 0.0),
            exit=float(config.get(ThresholdSignalModule.exit_threshold, 0.0) or 0.0),
            quantile_entry=float(config.get(ThresholdSignalModule.quantile_entry, 0.8) or 0.8),
            quantile_exit=float(config.get(ThresholdSignalModule.quantile_exit, 0.6) or 0.6),
            previous=previous_selection.get("long", frozenset()),
        )
    if side_mode in {"short_only", "long_short_spread"}:
        short_members = _select_threshold_side(
            signal_value,
            mode=mode,
            positive_side=False,
            entry=float(config.get(ThresholdSignalModule.entry_threshold, 0.0) or 0.0),
            exit=float(config.get(ThresholdSignalModule.exit_threshold, 0.0) or 0.0),
            quantile_entry=float(config.get(ThresholdSignalModule.quantile_entry, 0.8) or 0.8),
            quantile_exit=float(config.get(ThresholdSignalModule.quantile_exit, 0.6) or 0.6),
            previous=previous_selection.get("short", frozenset()),
        )

    selection = {"long": long_members, "short": short_members}
    if selection == previous_selection and previous_weights is not None:
        return dict(previous_weights), selection
    return _signed_weights(state, ctx, strategy, long_members, short_members, side_mode), selection


def _select_threshold_side(
    signal_value: dict,
    *,
    mode: str,
    positive_side: bool,
    entry: float,
    exit: float,
    quantile_entry: float,
    quantile_exit: float,
    previous: frozenset,
) -> frozenset:
    if mode == "cross_section_quantile":
        entry_cutoff = _quantile_cutoff(signal_value, quantile_entry, positive_side=positive_side)
        exit_cutoff = _quantile_cutoff(signal_value, quantile_exit, positive_side=positive_side)
        return frozenset(
            product for product, value in signal_value.items()
            if _passes_threshold(value, entry_cutoff, positive_side=positive_side)
            or (product in previous and _passes_threshold(value, exit_cutoff, positive_side=positive_side))
        )
    threshold_entry = entry if positive_side else -entry
    threshold_exit = exit if positive_side else -exit
    return frozenset(
        product for product, value in signal_value.items()
        if _passes_threshold(value, threshold_entry, positive_side=positive_side)
        or (product in previous and _passes_threshold(value, threshold_exit, positive_side=positive_side))
    )


def _quantile_cutoff(signal_value: dict, quantile: float, *, positive_side: bool) -> float:
    series = pd.Series(list(signal_value.values()), dtype="float64")
    q = min(max(float(quantile), 0.0), 1.0)
    return float(series.quantile(q if positive_side else 1.0 - q))


def _passes_threshold(value: float, threshold: float, *, positive_side: bool) -> bool:
    return value >= threshold if positive_side else value <= threshold


def _signed_weights(state, ctx, strategy, long_members: frozenset, short_members: frozenset, side_mode: str) -> dict[Any, float]:
    if side_mode == "long_short_spread":
        weights: dict[Any, float] = {}
        for product, weight in _allocate_weights(state, ctx, strategy, long_members).items():
            weights[product] = 0.5 * weight
        for product, weight in _allocate_weights(state, ctx, strategy, short_members).items():
            weights[product] = weights.get(product, 0.0) - 0.5 * weight
        return {product: weight for product, weight in weights.items() if abs(weight) > 1e-12}
    if side_mode == "short_only":
        return {product: -weight for product, weight in _allocate_weights(state, ctx, strategy, short_members).items()}
    return _allocate_weights(state, ctx, strategy, long_members)


def _rankable_signal_values(signal_value: dict, current_prices: dict | None, tradable_status: dict | None) -> dict:
    return _tradable_signal_values(signal_value, current_prices, tradable_status)


def _last_threshold_selection(state, strategy) -> dict[str, frozenset]:
    cached = state.target_store.strategy_selection_cache.get((strategy, "threshold"))
    if isinstance(cached, dict):
        return {
            "long": frozenset(cached.get("long", frozenset())),
            "short": frozenset(cached.get("short", frozenset())),
        }
    return {"long": frozenset(), "short": frozenset()}


def _store_threshold_selection(state, strategy, selection: dict[str, frozenset], weights: dict[Any, float]) -> None:
    state.target_store.strategy_selection_cache[(strategy, "threshold")] = selection
    state.target_store.strategy_established_target_weights[(strategy, "threshold")] = dict(weights)


register_strategy_intent_policy("threshold", ThresholdSignalIntentPolicy())
