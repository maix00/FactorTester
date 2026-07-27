"""Decode hook intent payloads into existing strategy-intent fields."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.engines.native.strategy_commands import command_from_payload
from tools.testers.backtest.modules.target import OrderDeltaIntent, TargetStrategyModule, TargetWeightIntent

from .commands import apply_strategy_command


def _apply_signal_intent(state: Any, ctx: Any) -> None:
    for strategy in ctx.active_strategies:
        for payload in ctx.payloads_for(strategy):
            if not isinstance(payload, dict):
                continue
            if payload.get("kind") == "strategy_hook_command":
                command = command_from_payload(payload)
                intent = apply_strategy_command(state, strategy, command, ctx.timestamp)
                if intent is not None:
                    ctx.set_for(TargetStrategyModule.trade_intent, strategy, intent)
                continue
            if payload.get("kind") != "strategy_hook_intent":
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
