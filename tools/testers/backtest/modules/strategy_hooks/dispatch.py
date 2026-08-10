"""Runtime callback dispatch; intent conversion lives in the adjacent module."""

from __future__ import annotations

import copy
from copy import deepcopy
from types import MappingProxyType
from typing import Any

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.market_events import MarketFeedEvent, MarketFeedEventKind
from tools.testers.backtest.engines.native.strategy import overridden_strategy_callbacks
from tools.testers.backtest.engines.native.orders.enums import OrderStatus
from tools.testers.backtest.engines.native.position_events import PositionEventKind
from tools.testers.backtest.engines.native.timer_events import TimerEvent, TimerSchedule, TimerCancel
from tools.testers.backtest.engines.native.strategy_hooks import (
    StrategyContext,
    intent_payload,
    normalize_hook_result,
)
from tools.testers.backtest.modules.causal_bar import CausalBar

from .fields import emitted_signal, emitted_timer


def _context_for(
    state: Any,
    ctx: Any,
    strategy: Any,
    *,
    include_current_prices: bool = True,
    data_overrides: dict[str, Any] | None = None,
) -> StrategyContext:
    from tools.testers.backtest.modules.market_data import MarketDataModule
    from tools.testers.backtest.modules.ledger_module import LedgerModule

    # Lifecycle flows deliberately do not declare a market snapshot.  Do not
    # read the field for them: the contract audit must distinguish a lifecycle
    # context from an event-time market context.
    prices = ctx.get(MarketDataModule.current_prices, {}) if include_current_prices else {}
    tradable = ctx.get(MarketDataModule.current_tradable_status, {}) if include_current_prices else {}
    positions: dict[Any, Any] = {}
    try:
        ledger = state.ledger_for_strategy(strategy)
        stored = ledger.get(LedgerModule.positions, {})
        if isinstance(stored, dict):
            # MappingProxyType protects the mapping only.  Copy position
            # records as well so a hook cannot mutate ledger-owned objects.
            positions = deepcopy(stored)
    except (AttributeError, KeyError):
        # Lightweight unit/scheduler tests may intentionally omit a ledger.
        pass
    data = {
        "current_prices": dict(prices) if isinstance(prices, dict) else {},
        "tradable_status": dict(tradable) if isinstance(tradable, dict) else {},
    }
    if data_overrides:
        data.update(data_overrides)
    for name, source in getattr(strategy, "_factortester_strategy_data", {}).items():
        if str(source) in data:
            data[str(name)] = data[str(source)]
    return StrategyContext(
        strategy=strategy,
        timestamp=ctx.timestamp,
        event_kind=ctx.event_kind,
        positions=MappingProxyType(positions),
        current_prices=MappingProxyType(dict(prices) if isinstance(prices, dict) else {}),
        run_start=_run_window_timestamp(state, strategy, "start_dt"),
        run_end=_run_window_timestamp(state, strategy, "end_dt"),
        parameters=getattr(strategy, "_factortester_strategy_parameters", {}),
        data=data,
    )


def _run_window_timestamp(state: Any, strategy: Any, name: str) -> Any:
    store = getattr(state, "run_window_store", None)
    window_for = getattr(store, "window_for", None)
    window = window_for(strategy) if callable(window_for) else None
    value = getattr(window, name, None)
    return getattr(value, "ts", value)


def _call_start(state: Any, ctx: Any) -> None:
    for strategy in ctx.active_strategies:
        result = strategy.on_start(
            _context_for(state, ctx, strategy, include_current_prices=False),
        )
        _emit_effects(ctx, strategy, result, allow_intents=False, allow_schedules=True)


def _call_stop(state: Any, ctx: Any) -> None:
    for strategy in ctx.active_strategies:
        result = strategy.on_stop(
            _context_for(state, ctx, strategy, include_current_prices=False),
        )
        _emit_effects(
            ctx, strategy, result, allow_intents=False,
            allow_schedules=True, allow_timer_schedule=False,
        )


def _call_market_feed(state: Any, ctx: Any) -> None:
    for strategy in ctx.active_strategies:
        for event in ctx.payloads_for(strategy):
            if not isinstance(event, MarketFeedEvent):
                raise TypeError("MARKET_FEED hook requires MarketFeedEvent payload")
            result = _specific_feed_hook(state, strategy, ctx, event)
            _emit_intents(ctx, strategy, result)


def _specific_feed_hook(state: Any, strategy: Any, ctx: Any, event: MarketFeedEvent) -> Any:
    hook_name = {
        MarketFeedEventKind.QUOTE: "on_quote",
        MarketFeedEventKind.TRADE: "on_trade",
        MarketFeedEventKind.BOOK_DELTA: "on_book_delta",
        MarketFeedEventKind.BOOK_SNAPSHOT: "on_book_snapshot",
    }.get(event.kind)
    if hook_name in overridden_strategy_callbacks(strategy):
        return getattr(strategy, hook_name)(
            _context_for(state, ctx, strategy), _feed_payload_snapshot(event.payload),
        )
    return strategy.on_market_feed(
        _context_for(state, ctx, strategy), copy.deepcopy(event),
    )


def _feed_payload_snapshot(payload: Any) -> Any:
    return copy.deepcopy(payload)


def _call_bar(state: Any, ctx: Any) -> None:
    from tools.testers.backtest.modules.market_data import MarketDataModule

    snapshot = ctx.get(MarketDataModule.current_market_snapshot, {}) or {}
    for strategy in ctx.active_strategies:
        for bar in ctx.payloads_for(strategy):
            causal_bar = _causal_bar_for_hook(ctx, bar, snapshot)
            _emit_intents(
                ctx,
                strategy,
                strategy.on_bar(
                    _context_for(
                        state, ctx, strategy,
                        data_overrides={"bar": causal_bar},
                    ),
                    copy.deepcopy(bar),
                ),
            )


def _causal_bar_for_hook(ctx: Any, payload: Any, snapshot: Any) -> CausalBar:
    """Build a read-only typed BAR view without changing the legacy payload."""
    available_at = pd.Timestamp(ctx.timestamp)
    bar_end = available_at
    if isinstance(payload, dict):
        bar_end = pd.Timestamp(payload.get("bar_end", bar_end))
        available_at = pd.Timestamp(payload.get("available_at", available_at))

    values: dict[Any, dict[str, Any]] = {}
    if isinstance(snapshot, dict):
        for field_name, products in snapshot.items():
            # Term-structure curves are table objects with their own lifecycle;
            # do not smuggle a mutable DataFrame through the scalar BAR view.
            if field_name == "TERM_STRUCTURE":
                continue
            if not isinstance(products, dict):
                continue
            for product, value in products.items():
                if isinstance(value, (dict, list, set, tuple)):
                    continue
                values.setdefault(product, {})[str(field_name)] = value
    return CausalBar(
        bar_end=bar_end,
        available_at=available_at,
        values=values,
    )


def _call_order_event(state: Any, ctx: Any) -> None:
    _call_order_event_impl(state, ctx, status_axis=False)


def _call_order_status_event(state: Any, ctx: Any) -> None:
    _call_order_event_impl(state, ctx, status_axis=True)


def _call_timer(state: Any, ctx: Any) -> None:
    for strategy in ctx.active_strategies:
        for event in ctx.payloads_for(strategy):
            if not isinstance(event, TimerEvent):
                raise TypeError("TIMER hook requires TimerEvent payload")
            result = strategy.on_timer(_context_for(state, ctx, strategy), event)
            _emit_effects(ctx, strategy, result, allow_intents=True, allow_schedules=True)


def _call_order_event_impl(state: Any, ctx: Any, *, status_axis: bool) -> None:
    for strategy in ctx.active_strategies:
        if not status_axis and _uses_order_status_axis(state, strategy):
            continue
        for order in ctx.payloads_for(strategy):
            result = _specific_order_hook(
                strategy, _context_for(state, ctx, strategy), _order_snapshot(order),
            )
            _emit_intents(ctx, strategy, result)


def _uses_order_status_axis(state: Any, strategy: Any) -> bool:
    config_for = getattr(state, "config_for", None)
    if not callable(config_for):
        return False
    return config_for(strategy).uses_flow("strategy_runtime_on_order_status_event")


def _order_snapshot(order: Any) -> Any:
    """Detach an order callback from the authoritative lifecycle object."""

    snapshot = copy.copy(order)
    if hasattr(order, "fields"):
        snapshot.fields = dict(getattr(order, "fields", {}) or {})
    return snapshot


def _call_position_event(state: Any, ctx: Any) -> None:
    for strategy in ctx.active_strategies:
        for position_event in ctx.payloads_for(strategy):
            result = _specific_position_hook(
                strategy, _context_for(state, ctx, strategy), position_event,
            )
            _emit_effects(ctx, strategy, result)


def _specific_order_hook(strategy: Any, context: StrategyContext, order: Any) -> Any:
    hook_name = {
        OrderStatus.BLOCKED: "on_order_blocked",
        OrderStatus.SUBMITTED: "on_order_submitted",
        OrderStatus.ACCEPTED: "on_order_accepted",
        OrderStatus.PARTIALLY_FILLED: "on_order_partially_filled",
        OrderStatus.PENDING_CANCEL: "on_order_pending_cancel",
        OrderStatus.PENDING_UPDATE: "on_order_pending_update",
        OrderStatus.FILLED: "on_order_filled",
        OrderStatus.CANCELLED: "on_order_canceled",
        OrderStatus.REJECTED: "on_order_rejected",
        OrderStatus.EXPIRED: "on_order_expired",
    }.get(getattr(order, "status", None))
    if hook_name in overridden_strategy_callbacks(strategy):
        return getattr(strategy, hook_name)(context, order)
    return strategy.on_order_event(context, order)


def _specific_position_hook(
    strategy: Any, context: StrategyContext, position_event: Any,
) -> Any:
    hook_name = {
        PositionEventKind.OPENED: "on_position_opened",
        PositionEventKind.CHANGED: "on_position_changed",
        PositionEventKind.CLOSED: "on_position_closed",
    }.get(getattr(position_event, "kind", None))
    if hook_name in overridden_strategy_callbacks(strategy):
        return getattr(strategy, hook_name)(context, position_event)
    return strategy.on_position_event(context, position_event)


def _emit_intents(ctx: Any, strategy: Any, result: Any) -> None:
    _emit_effects(ctx, strategy, result, allow_intents=True, allow_schedules=True)


def _emit_effects(
    ctx: Any,
    strategy: Any,
    result: Any,
    *,
    allow_intents: bool = True,
    allow_schedules: bool = True,
    allow_timer_schedule: bool = True,
) -> None:
    for effect in normalize_hook_result(result):
        if isinstance(effect, TimerSchedule):
            if not allow_schedules or not allow_timer_schedule:
                raise ValueError("this strategy lifecycle hook cannot schedule timers")
            ctx.set_for(emitted_timer, strategy, effect)
            continue
        if isinstance(effect, TimerCancel):
            if not allow_schedules:
                raise ValueError("this strategy lifecycle hook cannot cancel timers")
            ctx.set_for(emitted_timer, strategy, effect)
            continue
        if not allow_intents:
            raise ValueError("this strategy lifecycle hook cannot emit a trading intent")
        ctx.set_for(
            emitted_signal, strategy,
            EventDraft(EventKind.SIGNAL, ctx.timestamp, strategy, payload=intent_payload(effect)),
        )
