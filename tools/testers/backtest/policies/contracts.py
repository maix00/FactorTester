"""Stable contracts hosted by a StrategyBook policy container."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from tools.testers.backtest.engines.native.ledger import Ledger

OrderRoutingPolicy = Callable[[object, object], str | Ledger]
CashAvailabilityPolicy = Callable[[object, object, float, str], float]
OrderSizingPolicy = Callable[[object, object, object, dict[Any, float]], dict[Any, float]]
PendingOrderConflictPolicy = Callable[[object, object, object, object], None]
TradeDecisionMergePolicy = Callable[[object, object], object]
HierarchyConstraintPolicy = Callable[[object, object], object]
StrategyIntentPrecomputePolicy = Callable[[object, object, Sequence[object], object], None]


class StrategyIntentPolicy:
    """Own signal-to-intent semantics for one or more strategies."""

    def precompute_strategy_intents(
        self,
        state: object,
        ctx: object,
        strategies: Sequence[object],
    ) -> None:
        return None


@dataclass
class StrategyBookPolicies:
    """Resolve strategy policies and host cross-boundary override hooks."""

    order_routing: OrderRoutingPolicy | None = None
    cash_availability: CashAvailabilityPolicy | None = None
    order_sizing: OrderSizingPolicy | None = None
    pending_order_conflict: PendingOrderConflictPolicy | None = None
    trade_decision_merge: TradeDecisionMergePolicy | None = None
    hierarchy_constraints: HierarchyConstraintPolicy | None = None
    strategy_intent_by_alias: Mapping[str, StrategyIntentPolicy] = field(default_factory=dict)
    strategy_intent_precompute: StrategyIntentPrecomputePolicy | None = None

    def strategy_intent_for(
        self,
        strategy: object,
        default_policy: StrategyIntentPolicy,
    ) -> StrategyIntentPolicy:
        """Resolve a strategy-owned intent policy with a built-in fallback."""
        alias = str(getattr(strategy, "alias", strategy))
        return self.strategy_intent_by_alias.get(alias, default_policy)
