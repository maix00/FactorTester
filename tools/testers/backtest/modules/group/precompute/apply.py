"""Apply a compiled group target at its original causal event key."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from tools.testers.backtest.modules.target import TargetStrategyModule, target_weight_intent
from tools.testers.backtest.modules.group.runtime import record_target_trace


def apply_precomputed_target_intents(state, ctx, strategies: Sequence[object]) -> bool:
    from tools.testers.backtest.modules.group_membership import GroupMembershipModule

    if ctx.timestamp is None or any(
        state.target_store.precomputed_target_intents.get(strategy) is None
        for strategy in strategies
    ):
        return False
    for strategy in strategies:
        table = state.target_store.precomputed_target_intents[strategy]
        intent = table.get(_event_key(ctx, strategy)) or table.get(pd.Timestamp(ctx.timestamp))
        if intent is None:
            intent = target_weight_intent({}, reason="precomputed_target_missing")
        ctx.set_for(GroupMembershipModule.target_weights, strategy, intent.weights)
        ctx.set_for(TargetStrategyModule.trade_intent, strategy, intent)
        record_target_trace(state, strategy, ctx.timestamp, intent.weights)
    return True


def _event_key(ctx, strategy) -> Any:
    try:
        draft = ctx.draft_for(strategy)
    except Exception:
        return pd.Timestamp(ctx.timestamp)
    return draft.index_key if draft.index_key is not None else pd.Timestamp(ctx.timestamp)
