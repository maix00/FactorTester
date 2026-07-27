"""Decode hook intent payloads into existing strategy-intent fields."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.strategy_commands import command_from_payload
from tools.testers.backtest.modules.target import OrderDeltaIntent, TargetStrategyModule, TargetWeightIntent

from .commands import apply_strategy_command
from .fields import emitted_signal


def _apply_signal_intent(state: Any, ctx: Any) -> None:
    for strategy in ctx.active_strategies:
        for payload in ctx.payloads_for(strategy):
            if not isinstance(payload, dict):
                continue
            if payload.get("kind") == "strategy_runtime_command":
                command = command_from_payload(payload)
                intent = apply_strategy_command(state, strategy, command, ctx.timestamp)
                if intent is not None:
                    ctx.set_for(TargetStrategyModule.trade_intent, strategy, intent)
                _emit_command_lifecycle_event(state, ctx, strategy, command)
                continue
            if payload.get("kind") != "strategy_runtime_intent":
                continue
            reason = str(payload.get("reason") or "hook")
            intent_kind = payload.get("intent_kind")
            if intent_kind == "target_weights":
                intent = TargetWeightIntent(dict(payload.get("weights") or {}), reason=reason)
                ctx.set_for(TargetStrategyModule.target_weights, strategy, intent.weights)
            elif intent_kind == "order_deltas":
                intent = OrderDeltaIntent(dict(payload.get("deltas") or {}), reason=reason)
            else:
                raise ValueError(f"unknown strategy hook intent kind: {intent_kind!r}")
            ctx.set_for(TargetStrategyModule.trade_intent, strategy, intent)


def _emit_command_lifecycle_event(
    state: Any,
    ctx: Any,
    strategy: Any,
    command: Any,
) -> None:
    """Make direct cancel/replace commands observable to order hooks.

    Commands are decoded in a SIGNAL flow, while the order hook surface is
    intentionally driven by ORDER events.  Queueing the affected terminal
    order here keeps that distinction explicit and prevents a cancel callback
    from being silently skipped.
    """

    kind = getattr(command, "kind", None)
    if getattr(kind, "value", kind) not in {"cancel_order", "replace_order"}:
        return
    order_id = str(getattr(command, "order_id", "") or "")
    order_store = getattr(state, "order_store", None)
    order = getattr(order_store, "orders_by_id", {}).get(order_id)
    if order is None or not getattr(order.status, "terminal", False):
        return
    ctx.set_for(
        emitted_signal,
        strategy,
        EventDraft(EventKind.ORDER_STATUS, ctx.timestamp, strategy, order),
    )
