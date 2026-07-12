"""GroupMembershipModule — one concrete signal-to-order implementation:
ranks products by signal_value and assigns equal weight to whichever
n_groups-way quantile bucket group_index selects. ThresholdSignalModule
(not built this round) would be the other mutually-exclusive
implementation of the same role (buy above a threshold, sell below it) --
selected per strategy via StrategyConfig.active_flow_names, same mechanism
as FactorSignalModule's "signal_live"/"signal_precomputed" pair.

`schedule_order_execution` is also defined here (not a separate module)
since "turn target_weights into a delayed EventKind.ORDER dispatch, with
cancellation of any still-pending order for the same (strategy, product)"
is intrinsic to whichever concrete signal-to-order strategy is active --
it is not its own reusable concern independent of GroupMembershipModule/
ThresholdSignalModule.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, cast

import numpy as np
import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.fields import FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.engines.native.order import OrderStatus
from tools.testers.backtest.modules.time_index_lookup import row_at, signal_event_times, signal_timestamps
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    current_historical_fields_at,
    current_prices_table_for,
    current_prices_at,
    market_price_tables_for,
    historical_fields_for_product,
    is_product_tradable,
    market_price_tables_for,
    resolved_bar_frequency_for_strategy,
    _historical_fields_for_strategy,
)
from tools.testers.backtest.modules.order_execution import OrderExecutionModule
from tools.testers.backtest.modules.order_construct import OrderConstructModule
from tools.testers.backtest.modules.engine import bar_price_visibility_timestamp
from tools.testers.backtest.modules.strategy_book import (
    StrategyIntentPolicy,
    strategy_book_store_for,
)
from tools.testers.backtest.modules.target import (
    TargetStrategyModule,
    register_strategy_intent_policy,
    target_weight_intent,
)
from tools.testers.backtest.modules.time_index_lookup import row_at_index_key


class GroupMembershipModule(TargetStrategyModule):
    key: ClassVar[str] = "group_strategy"  # matches the existing frontend
        # SettingModule("group_strategy", ...) / chip module references --
        # this is the same concept the old framework called "分组策略",
        # not a new parallel grouping
    label: ClassVar[str] = "分组隶属"

    split_count: ClassVar[FieldRef[int]] = FieldRef("split_count")
    group_index: ClassVar[FieldRef[int]] = FieldRef("group_index")
    target_weights: ClassVar[FieldRef[Any]] = TargetStrategyModule.target_weights  # dict[Product, float], Σ == 1
    execution_timing: ClassVar[FieldRef[str]] = FieldRef("execution_timing")  # fixed "next_bar"
    execution_delay_bars: ClassVar[FieldRef[int]] = FieldRef("execution_delay_bars")
    dispatched_order_events: ClassVar[FieldRef[Any]] = FieldRef("dispatched_order_events")  # push-only, never read
    position_policy: ClassVar[FieldRef[str]] = FieldRef("position_policy")  # "rebalance_to_target"|"buy_and_hold"
    rebalance_trigger: ClassVar[FieldRef[str]] = FieldRef("rebalance_trigger")
        # "on_factor_signal"|"membership_change" -- "scheduled" (pure calendar,
        # independent of factor signals) is not implemented this round: it
        # would need its own calendar-driven Flow producing SIGNAL events on
        # a fixed schedule rather than at signal_align's factor-derived
        # timestamps, which doesn't exist yet.
    allocation_policy: ClassVar[FieldRef[str]] = FieldRef("allocation_policy")
        # "equal_notional"|"inverse_volatility"|"equal_margin".  equal_margin
        # is an explicit comparison allocator: equal margin budget, not equal
        # risk and not the default research semantics.
    volatility_lookback: ClassVar[FieldRef[int]] = FieldRef("volatility_lookback")
    volatility_warmup: ClassVar[FieldRef[str]] = FieldRef("volatility_warmup")
        # "equal_notional"|"error" -- what to do for a product whose trailing
        # window doesn't have enough history yet to compute a volatility estimate
    product_mask_names: ClassVar[FieldRef[Any]] = FieldRef("product_mask_names")
        # Optional derived-group product filter.  It must be applied after the
        # full-universe group membership bucket is computed, so derived groups
        # mean "parent bucket intersected with mask", not "re-rank inside mask".

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "split_count": FieldDefinition(
            public=True, label="分组数", default=5, frontend_only_default=True, control_template="number", tab="group_strategy",
            chip_template="分组数: {value}", tab_label="分组数量", tab_order=90,
            scope_policy="group_only",
        ),
        "group_index": FieldDefinition(
            public=True, label="分组", default=1, frontend_only_default=True, control_template="number", tab="group_strategy",
            chip_template="分组: {value}", tab_label="分组数量", tab_order=90,
            scope_policy="group_only", display_offset=1,
        ),
        "execution_timing": FieldDefinition(
            public=False, label="成交时机", default="next_bar", control_template="select", tab="order",
            options=(("next_bar", "下一 bar 开盘成交"),),
            chip_template="成交时机: {value}", tab_label="订单执行", tab_order=120,
        ),
        "execution_delay_bars": FieldDefinition(
            public=False, label="延迟", default=1, control_template="number", tab="order",
            visible_when={"execution_timing": ("next_bar",)},
            chip_template="延迟: {value}bar", tab_label="订单执行", tab_order=120,
        ),
        "position_policy": FieldDefinition(
            public=True, label="持仓", default="rebalance_to_target", control_template="select", tab="position_policy",
            options=(("rebalance_to_target", "按目标调仓"), ("buy_and_hold", "买入持有")),
            chip_template="持仓: {value}", tab_label="持仓政策", tab_order=80,
        ),
        "rebalance_trigger": FieldDefinition(
            public=True, label="调仓", default="on_factor_signal", control_template="select", tab="rebalance_trigger",
            options=(("on_factor_signal", "因子信号事件"), ("membership_change", "成员变化事件")),
            chip_template="调仓: {value}", tab_label="调仓触发", tab_order=70,
        ),
        "allocation_policy": FieldDefinition(
            public=True, label="分配", default="equal_notional", control_template="select", tab="target_allocation",
            options=(("equal_notional", "等市值"), ("inverse_volatility", "等风险（波动率倒数）"), ("equal_margin", "等保证金（对照）")),
            chip_template="分配: {value}", tab_label="目标分配", tab_order=60,
        ),
        "volatility_lookback": FieldDefinition(
            public=True, label="波动窗口", default=20, control_template="number", tab="target_allocation",
            visible_when={"allocation_policy": ("inverse_volatility",)},
            chip_template="波动窗口: {value}", tab_label="目标分配", tab_order=60,
        ),
        "volatility_warmup": FieldDefinition(
            public=True, label="预热", default="equal_notional", control_template="select", tab="target_allocation",
            options=(("equal_notional", "预热期使用等市值并记录"), ("error", "数据不足即报错")),
            visible_when={"allocation_policy": ("inverse_volatility",)},
            chip_template="预热: {value}", tab_label="目标分配", tab_order=60,
        ),
        "product_mask_names": FieldDefinition(public=False, label="品种范围", default=None),
    }

    group_quantile_membership: ClassVar[Flow] = Flow(
        "group_quantile_membership",
        inputs=(
            FactorSignalModule.signal_value, split_count, group_index,
            MarketDataModule.current_historical_fields,
        ),
        outputs=(target_weights, TargetStrategyModule.trade_intent),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        description="计算分组隶属",
        order=10, compute=lambda state, ctx: _group_quantile_membership(state, ctx),
    )
    schedule_order_execution: ClassVar[Flow] = Flow(
        "schedule_order_execution",
        inputs=(OrderConstructModule.orders,), outputs=(dispatched_order_events,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=40,
        after=(OrderConstructModule.construct_orders,),
        description="登记订单执行事件",
        compute=lambda state, ctx: _schedule_order_execution(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (
        group_quantile_membership, schedule_order_execution,
    )


def _group_quantile_membership(state, ctx) -> None:
    """`position_policy="buy_and_hold"`: once a strategy has computed its
    first non-empty target_weights, every later SIGNAL event reuses that
    exact same allocation (cached on the shared target strategy store)
    instead of recomputing from the current signal_value -- real holding
    behavior, not "rebalance every period but happen to get the same
    answer." `OrderConstructModule.size_order` naturally produces zero deltas
    once the position already matches that frozen target, so no further
    trading happens without needing a separate skip-flag anywhere else.

    `rebalance_trigger="membership_change"`: even though the signal moved,
    if the resulting bucket membership SET is unchanged from last time,
    reuse the previous target_weights instead of the freshly computed (but
    equivalent) one -- avoids needless turnover/fees on a signal that
    didn't actually change who's in or out of the group. This reuse is only
    valid under `allocation_policy="equal_notional"`, where weight is a
    pure function of membership size (same set, same size -> same weights,
    provably); `inverse_volatility`/`equal_margin` derive weight from
    time-varying inputs that drift even when membership doesn't, so this
    trigger rejects those allocation policies outright rather than serve a
    silently stale allocation. "scheduled" is not implemented (see field
    docstring)."""
    precomputed = _apply_precomputed_target_intents(state, ctx)
    if precomputed:
        return

    store = state.target_store
    established = store.strategy_established_target_weights
    last_membership = store.strategy_selection_cache

    # Every strategy sharing a factor's precomputed schedule is dispatched
    # in this same SIGNAL batch (ctx.active_strategies), so their filtered
    # signal_value is often byte-identical across group_index=0..n-1 -- only
    # the bucket boundaries differ. Rank once per distinct signal_value
    # content, not once per strategy: cache key is the actual (product,
    # value) content (not a factor/schedule identity derived indirectly),
    # so two strategies only ever share a cached ranking when their inputs
    # are provably the same, never by coincidence of unrelated keys lining
    # up. split_count is deliberately excluded from the key -- the ranked
    # order doesn't depend on it, only the start/end slice does, so
    # strategies sharing signal_value can share a ranking even with
    # different split_count.
    ranked_cache: dict[frozenset, list[tuple[Any, float]]] = {}
    # A derived group shares its parent's split_count/group_index exactly
    # (only product_mask_names differs -- "parent bucket intersected with
    # mask", per product_mask_names' own field docstring), so once a
    # (signal content, n_groups, group_index) triple has been sliced into a
    # raw bucket, a strategy with the identical triple can reuse that raw
    # membership directly and just re-apply its own mask, instead of
    # re-slicing ranked from scratch.
    bucket_cache: dict[tuple[frozenset, int, int], frozenset] = {}

    for strategy in ctx.active_strategies:
        config = state.config_for(strategy)
        policy = config.get(GroupMembershipModule.position_policy, "rebalance_to_target")
        if policy == "buy_and_hold" and strategy in established:
            ctx.set_for(GroupMembershipModule.target_weights, strategy, established[strategy])
            ctx.set_for(TargetStrategyModule.trade_intent, strategy, target_weight_intent(
                established[strategy], reason="buy_and_hold_established_target"))
            continue

        trigger = config.get(GroupMembershipModule.rebalance_trigger, "on_factor_signal")
        if trigger == "scheduled":
            raise NotImplementedError(
                'rebalance_trigger="scheduled" requires a calendar-driven SIGNAL '
                "schedule independent of factor timing, not implemented this round")
        if trigger == "membership_change":
            allocation_policy = config.get(GroupMembershipModule.allocation_policy, "equal_notional")
            if allocation_policy != "equal_notional":
                raise ValueError(
                    'rebalance_trigger="membership_change" only reduces turnover correctly '
                    'under allocation_policy="equal_notional" -- weight there is a pure '
                    "function of membership size, so \"same membership\" really does mean "
                    f'"same weights". allocation_policy={allocation_policy!r} computes weights '
                    "from time-varying inputs (trailing volatility / current margin ratios) that "
                    "drift even when membership does not, so reusing the previous weights here "
                    'would silently serve a stale, no-longer-risk-balanced allocation. Use '
                    'rebalance_trigger="on_factor_signal" with this allocation_policy instead.'
                )

        signal_value = _tradable_signal_values(
            ctx.get_for(FactorSignalModule.signal_value, strategy, {}),
            ctx.get(MarketDataModule.current_prices),
            ctx.get(MarketDataModule.current_tradable_status, None),
        )
        n_groups = config.get(GroupMembershipModule.split_count, 1)
        group_index = config.get(GroupMembershipModule.group_index, 0)
        if not signal_value or n_groups <= 0:
            ctx.set_for(GroupMembershipModule.target_weights, strategy, {})
            ctx.set_for(TargetStrategyModule.trade_intent, strategy, target_weight_intent(
                {}, reason="empty_group_membership"))
            continue
        cache_key = frozenset(signal_value.items())
        ranked = ranked_cache.get(cache_key)
        if ranked is None:
            # Descending: group_index=0 ("第1组") is the highest-factor-value
            # bucket, group_index=n_groups-1 is the lowest -- the highest
            # factor value belongs in the first group. Secondary key on
            # product name makes tie-breaking deterministic by construction
            # (not an accident of dict/set iteration order, which for
            # UniqueNameObject-hashed products can vary run to run under
            # PYTHONHASHSEED randomization).
            ranked = sorted(signal_value.items(), key=lambda kv: (-kv[1], _product_name(kv[0])))
            ranked_cache[cache_key] = ranked
        bucket_key = (cache_key, n_groups, group_index)
        members = bucket_cache.get(bucket_key)
        if members is None:
            bucket_size = len(ranked) / n_groups
            start = round(group_index * bucket_size)
            end = round((group_index + 1) * bucket_size)
            members = frozenset(product for product, _ in ranked[start:end])
            bucket_cache[bucket_key] = members
        product_mask_names = config.get(GroupMembershipModule.product_mask_names)
        if product_mask_names:
            allowed = {str(name) for name in product_mask_names}
            members = frozenset(product for product in members if _product_name(product) in allowed)

        if trigger == "membership_change" and last_membership.get(strategy) == members:
            ctx.set_for(GroupMembershipModule.target_weights, strategy, established.get(strategy, {}))
            ctx.set_for(TargetStrategyModule.trade_intent, strategy, target_weight_intent(
                established.get(strategy, {}), reason="membership_unchanged"))
            continue

        weights = _allocate_weights(state, ctx, strategy, members)
        ctx.set_for(GroupMembershipModule.target_weights, strategy, weights)
        ctx.set_for(TargetStrategyModule.trade_intent, strategy, target_weight_intent(
            weights, reason="group_membership"))
        last_membership[strategy] = members
        established[strategy] = weights
        _record_target_trace(state, strategy, ctx.timestamp, weights)


def _apply_precomputed_target_intents(state, ctx) -> bool:
    if ctx.timestamp is None:
        return False
    for strategy in ctx.active_strategies:
        if state.target_store.precomputed_target_intents.get(strategy) is None:
            return False
    applied = False
    for strategy in ctx.active_strategies:
        table = state.target_store.precomputed_target_intents[strategy]
        key = _target_intent_event_key(ctx, strategy)
        intent = table.get(key)
        if intent is None:
            intent = table.get(pd.Timestamp(ctx.timestamp))
        if intent is None:
            ctx.set_for(GroupMembershipModule.target_weights, strategy, {})
            ctx.set_for(TargetStrategyModule.trade_intent, strategy, target_weight_intent(
                {}, reason="precomputed_target_missing"))
            applied = True
            continue
        ctx.set_for(GroupMembershipModule.target_weights, strategy, intent.weights)
        ctx.set_for(TargetStrategyModule.trade_intent, strategy, intent)
        _record_target_trace(state, strategy, ctx.timestamp, intent.weights)
        applied = True
    return applied


def _target_intent_event_key(ctx, strategy) -> Any:
    try:
        draft = ctx.draft_for(strategy)
    except Exception:
        return pd.Timestamp(ctx.timestamp)
    return draft.index_key if draft.index_key is not None else pd.Timestamp(ctx.timestamp)


class _TargetPrecomputeContext:
    def __init__(self, *, timestamp: pd.Timestamp, prices: dict, historical_fields: dict, strategy_fields: dict[Any, dict]) -> None:
        self.timestamp = timestamp
        self._values = {
            MarketDataModule.current_prices: prices,
            MarketDataModule.current_historical_fields: historical_fields,
        }
        self._strategy_fields = strategy_fields

    def get(self, ref, default=None):
        return self._values.get(ref, default)

    def get_for(self, ref, strategy, default=None):
        if ref is MarketDataModule.current_historical_fields:
            return self._strategy_fields.get(strategy, default)
        return default


class GroupMembershipIntentPolicy(StrategyIntentPolicy):
    def precompute_strategy_intents(self, state: object, ctx: object, strategies: Sequence[object]) -> None:
        _precompute_group_membership_target_intents(state, ctx, strategies)


def _precompute_group_membership_target_intents(state, ctx, strategies) -> None:
    store = state.target_store
    signal_store = state.factor_signal_store
    fallback_strategies: list[Any] = []
    by_event: dict[Any, list[tuple[Any, Any, dict]]] = {}
    strategies_by_table: dict[int, tuple[pd.DataFrame, list[Any]]] = {}
    for strategy in strategies:
        table = signal_store.precomputed_table_for(strategy)
        if table is None:
            continue
        if not _can_vectorize_group_precompute(state, strategy):
            fallback_strategies.append(strategy)
            continue
        key = id(table)
        if key not in strategies_by_table:
            strategies_by_table[key] = (table, [])
        strategies_by_table[key][1].append(strategy)
        store.precomputed_target_intents.setdefault(strategy, {})

    for table, table_strategies in strategies_by_table.values():
        if _precompute_group_membership_target_intents_vectorized(state, table, table_strategies):
            continue
        for strategy in table_strategies:
            fallback_strategies.append(strategy)

    for strategy in fallback_strategies:
        table = signal_store.precomputed_table_for(strategy)
        if table is None:
            continue
        store.precomputed_target_intents.setdefault(strategy, {})
        for event_time in signal_event_times(table):
            by_event.setdefault(event_time.index_key, []).append(
                (strategy, event_time, _signal_values_from_table(table, event_time.index_key))
            )

    established: dict[Any, dict[Any, float]] = {}
    last_membership: dict[Any, frozenset | None] = {}
    ordered_events = sorted(
        by_event.items(),
        key=lambda item: cast(pd.Timestamp, item[1][0][1].timestamp),
    )
    for _event_key, items in ordered_events:
        timestamp = cast(pd.Timestamp, items[0][1].timestamp)
        prices = current_prices_at(state, timestamp)
        needs_historical_fields = any(
            state.config_for(strategy).get(GroupMembershipModule.allocation_policy, "equal_notional") == "equal_margin"
            for strategy, _event_time, _signal_value in items
        )
        base_fields = current_historical_fields_at(state, timestamp) if needs_historical_fields else {}
        strategy_fields_cache: dict[Any, dict] = {}
        ranked_cache: dict[frozenset, list[tuple[Any, float]]] = {}
        bucket_cache: dict[tuple[frozenset, int, int], frozenset] = {}
        for strategy, event_time, signal_value in items:
            config = state.config_for(strategy)
            if needs_historical_fields:
                ledger = state.ledger_for_strategy(strategy)
                strategy_fields = strategy_fields_cache.get(strategy)
                if strategy_fields is None:
                    strategy_fields = _historical_fields_for_strategy(
                        base_fields,
                        config,
                        timestamp,
                        ledger_config=state.ledger_config_for(ledger),
                    )
                    strategy_fields_cache[strategy] = strategy_fields
            else:
                strategy_fields = {}
            pre_ctx = _TargetPrecomputeContext(
                timestamp=timestamp,
                prices=prices,
                historical_fields=base_fields,
                strategy_fields={strategy: strategy_fields},
            )
            weights, members, reason = _compute_group_target_weights(
                state,
                pre_ctx,
                strategy,
                signal_value,
                established=established.get(strategy),
                last_membership=last_membership.get(strategy),
                ranked_cache=ranked_cache,
                bucket_cache=bucket_cache,
            )
            if reason not in {"buy_and_hold_established_target", "membership_unchanged"}:
                established[strategy] = weights
                last_membership[strategy] = members
            intent = target_weight_intent(weights, reason=f"precomputed_{reason}")
            store.precomputed_target_intents[strategy][event_time.index_key] = intent
            store.precomputed_target_intents[strategy][timestamp] = intent


register_strategy_intent_policy("group", GroupMembershipIntentPolicy())


def _can_vectorize_group_precompute(state, strategy) -> bool:
    config = state.config_for(strategy)
    if config.get(GroupMembershipModule.position_policy, "rebalance_to_target") != "rebalance_to_target":
        return False
    if config.get(GroupMembershipModule.rebalance_trigger, "on_factor_signal") != "on_factor_signal":
        return False
    return config.get(GroupMembershipModule.allocation_policy, "equal_notional") in {
        "equal_notional",
        "inverse_volatility",
    }


def _precompute_group_membership_target_intents_vectorized(state, signal_table: pd.DataFrame, strategies: list[Any]) -> bool:
    if signal_table.empty or not strategies:
        return True
    if not isinstance(signal_table.index, pd.DatetimeIndex):
        return False
    price_table = current_prices_table_for(state)
    if not isinstance(price_table, pd.DataFrame) or price_table.empty:
        return False
    products = sorted(list(signal_table.columns), key=_product_name)
    if not products:
        return True
    try:
        signal = signal_table.loc[:, products]
        prices = price_table.reindex(signal.index, method="ffill").reindex(columns=products)
    except Exception:
        return False
    signal_index = cast(pd.DatetimeIndex, signal.index)
    rankable = signal.where(prices.notna() & (prices > 0))
    ranks = rankable.rank(axis=1, method="first", ascending=False, na_option="bottom")
    valid_counts = rankable.notna().sum(axis=1)
    event_times = list(signal_event_times(signal_table))
    if len(event_times) != len(signal_table.index):
        return False

    allocation_tables: dict[tuple[str, int], pd.DataFrame] = {}
    for strategy in strategies:
        config = state.config_for(strategy)
        n_groups = int(config.get(GroupMembershipModule.split_count, 1) or 1)
        group_index = int(config.get(GroupMembershipModule.group_index, 0) or 0)
        if n_groups <= 0:
            weights = pd.DataFrame(0.0, index=signal.index, columns=products)
        else:
            starts = (valid_counts * group_index / n_groups).round()
            ends = (valid_counts * (group_index + 1) / n_groups).round()
            membership = ranks.gt(starts, axis=0) & ranks.le(ends, axis=0) & rankable.notna()
            product_mask_names = config.get(GroupMembershipModule.product_mask_names)
            if product_mask_names:
                allowed = {str(name) for name in product_mask_names}
                membership = membership.loc[:, [product for product in membership.columns if _product_name(product) in allowed]]
            weights = _vectorized_group_weights(state, signal_index, membership, strategy, allocation_tables)
        _store_vectorized_target_intents(state, strategy, event_times, weights)
    return True


def _vectorized_group_weights(
    state,
    index: pd.DatetimeIndex,
    membership: pd.DataFrame,
    strategy,
    allocation_tables: dict[tuple[str, int], pd.DataFrame],
) -> pd.DataFrame:
    if membership.empty:
        return pd.DataFrame(0.0, index=index, columns=[])
    config = state.config_for(strategy)
    policy = config.get(GroupMembershipModule.allocation_policy, "equal_notional")
    counts = membership.sum(axis=1).replace(0, pd.NA)
    if policy != "inverse_volatility":
        return membership.astype(float).div(counts, axis=0).fillna(0.0)

    lookback = int(config.get(GroupMembershipModule.volatility_lookback, 20) or 20)
    cache_key = ("inverse_volatility", lookback)
    inv_vol = allocation_tables.get(cache_key)
    if inv_vol is None:
        table = current_prices_table_for(state)
        vol_table = _rolling_volatility_table(state, table, lookback)
        vol = vol_table.reindex(index, method="ffill").reindex(columns=membership.columns)
        inv_vol = (1.0 / vol).where(vol > 0)
        allocation_tables[cache_key] = inv_vol
    else:
        inv_vol = inv_vol.reindex(columns=membership.columns)
    raw = inv_vol.where(membership)
    warmup_membership = membership & raw.isna()
    warmup_counts = warmup_membership.sum(axis=1)
    member_counts = membership.sum(axis=1).replace(0, pd.NA)
    fallback_share = (warmup_counts / member_counts).fillna(0.0)
    weights = pd.DataFrame(0.0, index=index, columns=membership.columns)
    if warmup_membership.any().any():
        weights = weights.add(
            warmup_membership.astype(float).div(warmup_counts.replace(0, pd.NA), axis=0).mul(fallback_share, axis=0),
            fill_value=0.0,
        )
    raw = raw.fillna(0.0)
    raw_sum = raw.sum(axis=1).replace(0, pd.NA)
    weights = weights.add(raw.div(raw_sum, axis=0).mul(1.0 - fallback_share, axis=0), fill_value=0.0)
    return weights.fillna(0.0)


def _store_vectorized_target_intents(state, strategy, event_times: list[Any], weights: pd.DataFrame) -> None:
    table = state.target_store.precomputed_target_intents.setdefault(strategy, {})
    columns = list(weights.columns)
    values = weights.reindex(columns=columns).fillna(0.0).to_numpy(dtype=float, copy=False)
    row_count = len(weights.index)
    for pos, event_time in enumerate(event_times):
        if pos >= row_count:
            payload = {}
        else:
            row_values = values[pos]
            nonzero = np.flatnonzero(row_values)
            payload = {columns[int(col)]: float(row_values[int(col)]) for col in nonzero}
        intent = target_weight_intent(payload, reason="precomputed_group_membership")
        table[event_time.index_key] = intent
        table[event_time.timestamp] = intent


def _signal_values_from_table(table: pd.DataFrame, index_key: Any) -> dict:
    try:
        row = row_at_index_key(table, index_key) if index_key is not None else table.iloc[-1]
    except KeyError:
        return {}
    return {product: float(cast(Any, row[product])) for product in table.columns}


def _compute_group_target_weights(
    state,
    ctx,
    strategy,
    signal_value: dict,
    *,
    established: dict[Any, float] | None = None,
    last_membership: frozenset | None = None,
    ranked_cache: dict[frozenset, list[tuple[Any, float]]] | None = None,
    bucket_cache: dict[tuple[frozenset, int, int], frozenset] | None = None,
) -> tuple[dict, frozenset | None, str]:
    config = state.config_for(strategy)
    policy = config.get(GroupMembershipModule.position_policy, "rebalance_to_target")
    if policy == "buy_and_hold" and established is not None:
        return established, last_membership, "buy_and_hold_established_target"

    trigger = config.get(GroupMembershipModule.rebalance_trigger, "on_factor_signal")
    if trigger == "scheduled":
        raise NotImplementedError(
            'rebalance_trigger="scheduled" requires a calendar-driven SIGNAL '
            "schedule independent of factor timing, not implemented this round")
    if trigger == "membership_change":
        allocation_policy = config.get(GroupMembershipModule.allocation_policy, "equal_notional")
        if allocation_policy != "equal_notional":
            raise ValueError(
                'rebalance_trigger="membership_change" only reduces turnover correctly '
                'under allocation_policy="equal_notional" -- weight there is a pure '
                "function of membership size, so \"same membership\" really does mean "
                f'"same weights". allocation_policy={allocation_policy!r} computes weights '
                "from time-varying inputs (trailing volatility / current margin ratios) that "
                "drift even when membership does not, so reusing the previous weights here "
                'would silently serve a stale, no-longer-risk-balanced allocation. Use '
                'rebalance_trigger="on_factor_signal" with this allocation_policy instead.'
            )

    signal_value = _tradable_signal_values(
        signal_value,
        ctx.get(MarketDataModule.current_prices),
        ctx.get(MarketDataModule.current_tradable_status, None),
    )
    n_groups = config.get(GroupMembershipModule.split_count, 1)
    group_index = config.get(GroupMembershipModule.group_index, 0)
    if not signal_value or n_groups <= 0:
        return {}, None, "empty_group_membership"
    cache_key = frozenset(signal_value.items())
    ranked = ranked_cache.get(cache_key) if ranked_cache is not None else None
    if ranked is None:
        ranked = sorted(signal_value.items(), key=lambda kv: (-kv[1], _product_name(kv[0])))
        if ranked_cache is not None:
            ranked_cache[cache_key] = ranked
    bucket_key = (cache_key, n_groups, group_index)
    members = bucket_cache.get(bucket_key) if bucket_cache is not None else None
    if members is None:
        bucket_size = len(ranked) / n_groups
        start = round(group_index * bucket_size)
        end = round((group_index + 1) * bucket_size)
        members = frozenset(product for product, _ in ranked[start:end])
        if bucket_cache is not None:
            bucket_cache[bucket_key] = members
    product_mask_names = config.get(GroupMembershipModule.product_mask_names)
    if product_mask_names:
        allowed = {str(name) for name in product_mask_names}
        members = frozenset(product for product in members if _product_name(product) in allowed)

    if trigger == "membership_change" and last_membership == members:
        return established or {}, members, "membership_unchanged"

    return _allocate_weights(state, ctx, strategy, members), members, "group_membership"


def _tradable_signal_values(
    signal_value: dict,
    current_prices: dict | None,
    tradable_status: dict | None = None,
) -> dict:
    """The rankable cross-section: products must be tradable candidates AND
    have a real signal value.

    ``tradable_status`` is the market-mechanics gate. ``current_prices`` is
    only a compatibility fallback for tests/legacy callers that do not yet
    publish the explicit status field. A NaN factor value cannot be ranked --
    NaN comparisons are undefined under sorted()'s total-order assumption, so
    without this filter the product would silently land in an arbitrary bucket.
    Dropping it here also shrinks the bucket boundaries to the valid universe,
    matching cross-section quantile convention."""
    if not signal_value:
        return {}
    if tradable_status is not None and not tradable_status:
        return {}
    if tradable_status is None and current_prices is not None and not current_prices:
        return {}
    return {
        product: value for product, value in signal_value.items()
        if is_product_tradable(tradable_status, product, current_prices) and not pd.isna(value)
    }


def _product_name(product: Any) -> str:
    return str(getattr(product, "name", product))


def _record_target_trace(state, strategy, timestamp, weights: dict) -> None:
    """Only called on a genuinely fresh weights computation (not the
    buy_and_hold/membership_change "reuse the previous allocation" paths)
    -- matches the old target_trace contract where a trace entry's mere
    presence at a timestamp means "the target actually changed here"."""
    if timestamp is None:
        return
    state.target_store.record_target_trace(strategy, timestamp, weights)


def target_trace_for(state, strategy) -> dict:
    return state.target_store.target_trace_for(strategy)


def _allocate_weights(state, ctx, strategy, members: frozenset) -> dict:
    """`allocation_policy="equal_notional"` (default): every selected
    product gets 1/n of the allocation, regardless of its volatility.

    `allocation_policy="inverse_volatility"`: weight each product
    inversely to its trailing return volatility over `volatility_lookback`
    periods (ending at and including ctx.timestamp), normalized so the
    bucket's weights sum to 1 -- standard risk-parity-style sizing: a
    calmer product gets a bigger allocation than a choppier one with the
    same signal rank. A product without enough trailing history yet to
    estimate volatility falls back per `volatility_warmup`."""
    if not members:
        return {}
    config = state.config_for(strategy)
    policy = config.get(GroupMembershipModule.allocation_policy, "equal_notional")
    if policy == "equal_margin":
        return _allocate_equal_margin(state, ctx, strategy, members)
    if policy != "inverse_volatility":
        weight = 1.0 / len(members)
        return {product: weight for product in members}

    lookback = config.get(GroupMembershipModule.volatility_lookback, 20)
    warmup = config.get(GroupMembershipModule.volatility_warmup, "equal_notional")
    table = current_prices_table_for(state)
    inv_vol: dict = {}
    fallback_equal: list = []
    for product in members:
        vol = _trailing_volatility(state, table, product, ctx.timestamp, lookback)
        if vol is None or vol <= 0:
            if warmup == "error":
                raise ValueError(
                    f"insufficient price history to estimate volatility for {product!r} "
                    f"(need {lookback} trailing periods)")
            fallback_equal.append(product)
            continue
        inv_vol[product] = 1.0 / vol

    weights: dict = {}
    total_inv_vol = sum(inv_vol.values())
    # Reserve an equal-notional share of the bucket for warmup fallbacks,
    # then split the remainder by inverse volatility -- so a few
    # not-yet-estimable products don't silently zero out, but also don't
    # dilute the inverse-vol weighting of the rest beyond their fair share.
    fallback_share = len(fallback_equal) / len(members)
    remaining_share = 1.0 - fallback_share
    for product in fallback_equal:
        weights[product] = fallback_share / len(fallback_equal) if fallback_equal else 0.0
    if total_inv_vol > 0:
        for product, iv in inv_vol.items():
            weights[product] = remaining_share * iv / total_inv_vol
    return weights


def _allocate_equal_margin(state, ctx, strategy, members: frozenset) -> dict:
    ratios = ctx.get_for(
        MarketDataModule.current_historical_fields,
        strategy,
        ctx.get(MarketDataModule.current_historical_fields, {}),
    ) or {}
    raw: dict = {}
    for product in members:
        ratio = _margin_ratio_for_product(ratios, product)
        if ratio is not None and ratio > 0:
            raw[product] = 1.0 / ratio
    total = sum(raw.values())
    if total <= 0:
        weight = 1.0 / len(members)
        return {product: weight for product in members}
    return {product: value / total for product, value in raw.items()}


def _margin_ratio_for_product(fields: dict, product) -> float | None:
    values = historical_fields_for_product(fields, product)
    for key in ("LongMarginRatioByMoney", "ShortMarginRatioByMoney", "MarginRatio"):
        raw = values.get(key)
        if raw is None:
            continue
        try:
            value = float(cast(Any, raw))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _trailing_volatility(state, table, product, timestamp, lookback: int) -> float | None:
    if table is None or product not in table.columns:
        return None
    vol_table = _rolling_volatility_table(state, table, lookback)
    try:
        row = row_at(vol_table, timestamp, asof=True)
    except KeyError:
        return None
    std = row.get(product)
    return float(std) if pd.notna(std) else None


def _rolling_volatility_table(state, table: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Return causal trailing return volatility for every product.

    The previous implementation sliced each product series on every signal
    event.  For the default inverse-volatility allocator that means
    timestamp × strategy × product repeated pct_change/std work.  The price
    table is fixed after PRE_REPLAY, so compute the rolling table once per
    lookback and reuse it causally by timestamp.
    """
    key = (id(table), int(lookback))
    cache = state.target_store.rolling_volatility_tables
    cached = cache.get(key)
    if cached is not None:
        return cached
    returns = table.pct_change(fill_method=None)
    vol_table = returns.rolling(window=int(lookback), min_periods=int(lookback)).std()
    cache[key] = vol_table
    return vol_table


def _resolve_execution_schedule(state, ctx, strategy, product: Any | None = None) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    if ctx.timestamp is None:
        raise ValueError("execution scheduling requires an event timestamp")
    current_ts = cast(pd.Timestamp, ctx.timestamp)
    config = state.config_for(strategy)
    timing = config.get(GroupMembershipModule.execution_timing, "next_bar")
    basis = str(config.get(OrderExecutionModule.execution_price_basis, "open") or "open").lower()
    if timing != "next_bar":
        raise ValueError("order execution is fixed to next-bar open")
    if basis != "open":
        raise ValueError("order execution is fixed to next-bar open")
    delay = config.get(GroupMembershipModule.execution_delay_bars, 1)
    table = _execution_schedule_price_table(state, basis)
    if table is None:
        return current_ts, current_ts
    bar_freq = resolved_bar_frequency_for_strategy(state, strategy)
    freq_key = getattr(bar_freq, "name", str(bar_freq)) if bar_freq is not None else None
    product_key = str(getattr(product, "name", product)) if product is not None else None
    cache_key = (pd.Timestamp(current_ts).value, str(current_ts.tz), int(delay or 1), basis, freq_key, id(table), product_key)
    if cache_key in state.target_store.execution_schedule_cache:
        return state.target_store.execution_schedule_cache[cache_key]
    index = _execution_schedule_index(table, product)
    if len(index) == 0:
        state.target_store.execution_schedule_cache[cache_key] = None
        return None
    pos = index.get_indexer(pd.Index([current_ts]), method="bfill")[0]
    if pos < 0:
        state.target_store.execution_schedule_cache[cache_key] = None
        return None
    delay = max(int(delay or 1), 1)
    price_pos = pos + delay
    if price_pos >= len(index):
        state.target_store.execution_schedule_cache[cache_key] = None
        return None
    price_ts = cast(pd.Timestamp, index[price_pos])
    event_ts = bar_price_visibility_timestamp(index, price_pos=price_pos, basis=basis, config=config, bar_freq=bar_freq)
    schedule = (event_ts, price_ts)
    state.target_store.execution_schedule_cache[cache_key] = schedule
    return schedule


def _execution_schedule_price_table(state, basis: str) -> pd.DataFrame | None:
    tables = market_price_tables_for(state)
    table = tables.get(basis) if isinstance(tables, dict) else None
    if isinstance(table, pd.DataFrame) and not table.empty:
        return table
    fallback = current_prices_table_for(state)
    return fallback if isinstance(fallback, pd.DataFrame) and not fallback.empty else None


def _execution_schedule_index(table: pd.DataFrame, product: Any | None) -> pd.DatetimeIndex:
    if product is None or product not in table.columns:
        return signal_timestamps(table)
    series = table[product].dropna()
    if series.empty:
        return pd.DatetimeIndex([])
    return signal_timestamps(series)


def _resolve_execution_timestamp(state, ctx, strategy) -> pd.Timestamp:
    schedule = _resolve_execution_schedule(state, ctx, strategy)
    if schedule is None:
        raise ValueError("next-bar order execution has no future bar to target")
    event_ts, _price_ts = schedule
    return event_ts


def _schedule_order_execution(state, ctx) -> None:
    """Schedule orders and apply StrategyBook's pending-order conflict policy."""
    pending = state.order_store.pending_orders
    pending_conflict_policy = strategy_book_store_for(state).policies.pending_order_conflict

    drafts: list[EventDraft] = []
    for strategy in ctx.active_strategies:
        orders = ctx.get_for(OrderConstructModule.orders, strategy, [])
        for order in orders:
            if abs(float(getattr(order, "quantity", 0.0) or 0.0)) <= 1e-12 or order.get("reject_reason"):
                continue
            schedule = _resolve_execution_schedule(state, ctx, strategy, order.instrument)
            if schedule is None:
                continue
            execution_ts, price_ts = schedule
            key = (strategy, order.instrument)
            if pending_conflict_policy is not None:
                pending_conflict_policy(state, strategy, order, ctx.timestamp)
            else:
                stale = pending.get(key)
                if (
                    stale is not None
                    and stale.status == OrderStatus.SCHEDULED
                    and stale.get("price_timestamp", stale.timestamp) > ctx.timestamp
                ):
                    stale.status = OrderStatus.CANCELLED
            order.status = OrderStatus.SCHEDULED
            order.timestamp = execution_ts
            order.set("price_timestamp", price_ts)
            pending[key] = order
            drafts.append(EventDraft(EventKind.ORDER, execution_ts, strategy, order))
    if drafts:
        ctx.set(GroupMembershipModule.dispatched_order_events, drafts)  # push-only trigger
