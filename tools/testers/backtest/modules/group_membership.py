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

from typing import Any, ClassVar

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.engines.native.order import OrderStatus
from tools.testers.backtest.modules.time_index_lookup import series_up_to, signal_timestamps
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.order_book import OrderBookModule


class GroupMembershipModule(ExecutableModule):
    key: ClassVar[str] = "group_strategy"  # matches the existing frontend
        # SettingModule("group_strategy", ...) / chip module references --
        # this is the same concept the old framework called "分组策略",
        # not a new parallel grouping
    label: ClassVar[str] = "分组隶属"

    split_count: ClassVar[FieldRef[int]] = FieldRef("split_count")
    group_index: ClassVar[FieldRef[int]] = FieldRef("group_index")
    target_weights: ClassVar[FieldRef[Any]] = FieldRef("target_weights")  # dict[Product, float], Σ == 1
    execution_timing: ClassVar[FieldRef[str]] = FieldRef("execution_timing")  # "same_bar"|"next_bar"
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
        # "equal_notional"|"inverse_volatility" -- "equal_margin" (the old
        # third option, labeled "对照"/reference-only in the legacy UI) is
        # not implemented: its exact intended semantics relative to the
        # other two weren't well-defined enough to implement without
        # guessing, and it was explicitly a "comparison baseline", not a
        # mode anyone actually runs live.
    volatility_lookback: ClassVar[FieldRef[int]] = FieldRef("volatility_lookback")
    volatility_warmup: ClassVar[FieldRef[str]] = FieldRef("volatility_warmup")
        # "equal_notional"|"error" -- what to do for a product whose trailing
        # window doesn't have enough history yet to compute a volatility estimate

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "split_count": FieldDefinition(
            public=True, label="分组数", default=5, frontend_only_default=True, control_template="number", tab="group_strategy",
            chip_template="分组数: {value}", tab_label="分组数量", tab_order=90,
            scope_policy="group_only",
        ),
        "group_index": FieldDefinition(
            public=True, label="分组", default=1, frontend_only_default=True, control_template="number", tab="group_strategy",
            chip_template="分组: {value}", tab_label="分组数量", tab_order=90,
            scope_policy="group_only",
        ),
        "execution_timing": FieldDefinition(
            public=True, label="成交时机", default="next_bar", control_template="select", tab="order",
            options=(("same_bar", "本期成交"), ("next_bar", "下一期成交")),
            chip_template="成交时机: {value}", tab_label="订单执行", tab_order=120,
        ),
        "execution_delay_bars": FieldDefinition(
            public=True, label="延迟", default=1, control_template="number", tab="order",
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
            public=True, label="分配", default="inverse_volatility", control_template="select", tab="target_allocation",
            options=(("equal_notional", "等市值"), ("inverse_volatility", "等风险（波动率倒数）")),
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
    }

    group_quantile_membership: ClassVar[Flow] = Flow(
        "group_quantile_membership",
        inputs=(FactorSignalModule.signal_value, split_count, group_index),
        outputs=(target_weights,), phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        order=10, compute=lambda account, ctx: _group_quantile_membership(account, ctx),
    )
    schedule_order_execution: ClassVar[Flow] = Flow(
        "schedule_order_execution", inputs=(OrderBookModule.orders,), outputs=(),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=40,
        after=(OrderBookModule.construct_orders,),
        compute=lambda account, ctx: _schedule_order_execution(account, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (group_quantile_membership, schedule_order_execution)


def _group_quantile_membership(account, ctx) -> None:
    """`position_policy="buy_and_hold"`: once a strategy has computed its
    first non-empty target_weights, every later SIGNAL event reuses that
    exact same allocation (cached on `account.established_target_weights`)
    instead of recomputing from the current signal_value -- real holding
    behavior, not "rebalance every period but happen to get the same
    answer." `OrderBookModule.size_order` naturally produces zero deltas
    once the position already matches that frozen target, so no further
    trading happens without needing a separate skip-flag anywhere else.

    `rebalance_trigger="membership_change"`: even though the signal moved,
    if the resulting bucket membership SET is unchanged from last time
    (same products selected, equal weight within a bucket never differs
    unless membership size changes), reuse the previous target_weights
    instead of the freshly computed (but equivalent) one -- avoids
    needless turnover/fees on a signal that didn't actually change who's
    in or out of the group. "scheduled" is not implemented (see field
    docstring)."""
    established = getattr(account, "established_target_weights", None)
    if established is None:
        established = {}
        account.established_target_weights = established
    last_membership = getattr(account, "last_group_membership", None)
    if last_membership is None:
        last_membership = {}
        account.last_group_membership = last_membership

    for strategy in ctx.active_strategies:
        config = account.config_for(strategy)
        policy = config.get(GroupMembershipModule.position_policy, "rebalance_to_target")
        if policy == "buy_and_hold" and strategy in established:
            ctx.set_for(GroupMembershipModule.target_weights, strategy, established[strategy])
            continue

        trigger = config.get(GroupMembershipModule.rebalance_trigger, "on_factor_signal")
        if trigger == "scheduled":
            raise NotImplementedError(
                'rebalance_trigger="scheduled" requires a calendar-driven SIGNAL '
                "schedule independent of factor timing, not implemented this round")

        signal_value = ctx.get_for(FactorSignalModule.signal_value, strategy, {})
        n_groups = config.get(GroupMembershipModule.split_count, 1)
        group_index = config.get(GroupMembershipModule.group_index, 0)
        if not signal_value or n_groups <= 0:
            ctx.set_for(GroupMembershipModule.target_weights, strategy, {})
            continue
        ranked = sorted(signal_value.items(), key=lambda kv: kv[1])
        bucket_size = len(ranked) / n_groups
        start = round(group_index * bucket_size)
        end = round((group_index + 1) * bucket_size)
        bucket = ranked[start:end]
        members = frozenset(product for product, _ in bucket)

        if trigger == "membership_change" and last_membership.get(strategy) == members:
            ctx.set_for(GroupMembershipModule.target_weights, strategy, established.get(strategy, {}))
            continue

        weights = _allocate_weights(account, ctx, strategy, members)
        ctx.set_for(GroupMembershipModule.target_weights, strategy, weights)
        last_membership[strategy] = members
        established[strategy] = weights
        _record_target_trace(account, strategy, ctx.timestamp, weights)


def _record_target_trace(account, strategy, timestamp, weights: dict) -> None:
    """Only called on a genuinely fresh weights computation (not the
    buy_and_hold/membership_change "reuse the previous allocation" paths)
    -- matches the old target_trace contract where a trace entry's mere
    presence at a timestamp means "the target actually changed here"."""
    if timestamp is None:
        return
    trace = getattr(account, "target_trace", None)
    if trace is None:
        trace = {}
        account.target_trace = trace
    trace.setdefault(strategy, {})[timestamp.isoformat()] = {str(p): w for p, w in weights.items()}


def target_trace_for(account, strategy) -> dict:
    trace = getattr(account, "target_trace", {})
    return dict(trace.get(strategy, {}))


def _allocate_weights(account, ctx, strategy, members: frozenset) -> dict:
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
    config = account.config_for(strategy)
    policy = config.get(GroupMembershipModule.allocation_policy, "equal_notional")
    if policy != "inverse_volatility":
        weight = 1.0 / len(members)
        return {product: weight for product in members}

    lookback = config.get(GroupMembershipModule.volatility_lookback, 20)
    warmup = config.get(GroupMembershipModule.volatility_warmup, "equal_notional")
    table = getattr(account, "current_prices_table", None)
    inv_vol: dict = {}
    fallback_equal: list = []
    for product in members:
        vol = _trailing_volatility(table, product, ctx.timestamp, lookback)
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


def _trailing_volatility(table, product, timestamp, lookback: int) -> float | None:
    if table is None or product not in table.columns:
        return None
    prices = table[product]
    prices = series_up_to(prices, timestamp)
    if len(prices) < lookback + 1:
        return None
    window = prices.iloc[-(lookback + 1):]
    returns = window.pct_change().dropna()
    if returns.empty:
        return None
    std = returns.std()
    return float(std) if pd.notna(std) else None


def _resolve_execution_timestamp(account, ctx, strategy) -> pd.Timestamp:
    config = account.config_for(strategy)
    timing = config.get(GroupMembershipModule.execution_timing, "next_bar")
    if timing == "same_bar":
        return ctx.timestamp
    delay = config.get(GroupMembershipModule.execution_delay_bars, 1)
    table = getattr(account, "current_prices_table", None)
    if table is None:
        return ctx.timestamp
    index = signal_timestamps(table)
    pos = index.get_indexer([ctx.timestamp], method="bfill")[0]
    target_pos = min(pos + delay, len(index) - 1)
    return index[target_pos]


def _schedule_order_execution(account, ctx) -> None:
    """Cancellation of a still-pending order for the same (strategy,
    product) is done by mutating the queued Order object in place (the
    EventQueue holds the same object reference) -- not by emitting a new
    event kind.

    Only cancels a stale order whose own scheduled timestamp is STRICTLY
    AFTER this SIGNAL's timestamp -- one scheduled to fire AT this exact
    timestamp is already "in flight" (within EventKind ordering, SIGNAL
    always precedes ORDER at the same timestamp, so that order hasn't
    actually executed yet, but it's already past its decision point and
    due right now). Cancelling it here would make any execution_delay_bars
    >= 1 a structural no-op whenever signals recompute every period -- the
    very next signal would always cancel the previous one's order before
    it ever fires."""
    pending = getattr(account, "pending_orders", None)
    if pending is None:
        pending = {}
        account.pending_orders = pending

    drafts: list[EventDraft] = []
    for strategy in ctx.active_strategies:
        orders = ctx.get_for(OrderBookModule.orders, strategy, [])
        execution_ts = _resolve_execution_timestamp(account, ctx, strategy)
        for order in orders:
            key = (strategy, order.instrument)
            stale = pending.get(key)
            if (
                stale is not None and stale.status == OrderStatus.SCHEDULED
                and stale.timestamp > ctx.timestamp
            ):
                stale.status = OrderStatus.CANCELLED
            order.status = OrderStatus.SCHEDULED
            order.timestamp = execution_ts
            pending[key] = order
            drafts.append(EventDraft(EventKind.ORDER, execution_ts, strategy, order))
    if drafts:
        ctx.set(GroupMembershipModule.dispatched_order_events, drafts)  # push-only trigger
