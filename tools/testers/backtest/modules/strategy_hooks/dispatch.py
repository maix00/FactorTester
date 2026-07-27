"""Runtime callback dispatch; intent conversion lives in the adjacent module."""

from __future__ import annotations

import copy
from copy import deepcopy
from types import MappingProxyType
from typing import Any

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.market_events import MarketFeedEvent, MarketFeedEventKind
from tools.testers.backtest.engines.native.strategy import overridden_strategy_callbacks
from tools.testers.backtest.engines.native.orders.enums import OrderStatus
from tools.testers.backtest.engines.native.position_events import PositionEventKind
from tools.testers.backtest.engines.native.strategy_hooks import (
    StrategyContext,
    intent_payload,
    normalize_hook_result,
)

from .fields import emitted_signal


def _context_for(state: Any, ctx: Any, strategy: Any) -> StrategyContext:
    from tools.testers.backtest.modules.market_data import MarketDataModule
    from tools.testers.backtest.modules.ledger_module import LedgerModule

    prices = ctx.get(MarketDataModule.current_prices, {})
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
    return StrategyContext(
        strategy=strategy,
        timestamp=ctx.timestamp,
        event_kind=ctx.event_kind,
        positions=MappingProxyType(positions),
        current_prices=MappingProxyType(dict(prices) if isinstance(prices, dict) else {}),
    )


def _call_start(state: Any, ctx: Any) -> None:
    for strategy in ctx.active_strategies:
        result = strategy.on_start(_context_for(state, ctx, strategy))
        if normalize_hook_result(result):
            raise ValueError("on_start cannot emit an intent before a market timestamp")


def _call_stop(state: Any, ctx: Any) -> None:
    for strategy in ctx.active_strategies:
        result = strategy.on_stop(_context_for(state, ctx, strategy))
        if normalize_hook_result(result):
            raise ValueError("on_stop cannot emit a new trading intent")


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
    for strategy in ctx.active_strategies:
        for bar in ctx.payloads_for(strategy):
            _emit_intents(
                ctx, strategy,
                strategy.on_bar(_context_for(state, ctx, strategy), copy.deepcopy(bar)),
            )


def _call_order_event(state: Any, ctx: Any) -> None:
    _call_order_event_impl(state, ctx, status_axis=False)


def _call_order_status_event(state: Any, ctx: Any) -> None:
    _call_order_event_impl(state, ctx, status_axis=True)


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
            _emit_intents(ctx, strategy, result)


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
    for intent in normalize_hook_result(result):
        ctx.set_for(
            emitted_signal, strategy,
            EventDraft(EventKind.SIGNAL, ctx.timestamp, strategy, payload=intent_payload(intent)),
        )
