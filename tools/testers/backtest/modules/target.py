"""Common strategy intent state.

Concrete strategy modules such as group membership, long-short composition, or
technical rules produce trade intents in different ways. Target weights are one
intent representation, not the universal strategy abstraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase


@dataclass(frozen=True)
class TargetWeightIntent:
    weights: dict[Any, float]
    reason: str = "target_weights"


@dataclass(frozen=True)
class OrderDeltaIntent:
    deltas: dict[Any, float]
    reason: str = "order_deltas"


class TargetStrategyModule(ExecutableModule):
    """Base class for modules that produce strategy trade intents."""

    key: ClassVar[str] = "strategy_intent"
    label: ClassVar[str] = "策略意图"
    order: ClassVar[int] = 86

    trade_intent: ClassVar[FieldRef[Any]] = FieldRef("trade_intent")
    target_weights: ClassVar[FieldRef[Any]] = FieldRef("target_weights")
    strategy_kind: ClassVar[FieldRef[str]] = FieldRef("strategy_kind")

    precompute_strategy_intents: ClassVar[Flow] = Flow(
        "precompute_strategy_intents",
        inputs=(),
        outputs=(trade_intent, target_weights),
        phase=Phase.PRE_REPLAY,
        order=55,
        description="预计算策略意图",
        compute=lambda state, ctx: _precompute_strategy_intents(state, ctx),
        strategy_scoped=True,
    )
    flows: ClassVar[tuple[Flow, ...]] = (precompute_strategy_intents,)


def target_weight_intent(weights: dict[Any, float], *, reason: str) -> TargetWeightIntent:
    return TargetWeightIntent(dict(weights), reason=reason)


@dataclass
class TargetStore:
    strategy_established_target_weights: dict[Any, Any] = field(default_factory=dict)
    strategy_selection_cache: dict[Any, Any] = field(default_factory=dict)
    target_trace: dict[Any, dict[str, Any]] = field(default_factory=dict)
    rolling_volatility_tables: dict[tuple[int, int], Any] = field(default_factory=dict)
    precomputed_target_intents: dict[Any, dict[Any, TargetWeightIntent]] = field(default_factory=dict)
    execution_schedule_cache: dict[Any, Any] = field(default_factory=dict)

    def record_target_trace(self, strategy: Any, timestamp: Any, weights: dict[Any, Any]) -> None:
        if timestamp is None:
            return
        self.target_trace.setdefault(strategy, {})[timestamp.isoformat()] = {
            str(product): weight for product, weight in weights.items()
        }

    def target_trace_for(self, strategy: Any) -> dict[str, Any]:
        return dict(self.target_trace.get(strategy, {}))


_STRATEGY_INTENT_POLICIES: dict[str, Any] = {}


def register_strategy_intent_policy(strategy_kind: str, policy: Any) -> None:
    _STRATEGY_INTENT_POLICIES[str(strategy_kind)] = policy


def strategy_intent_policy_for(strategy_kind: str) -> Any | None:
    return _STRATEGY_INTENT_POLICIES.get(str(strategy_kind))


def _precompute_strategy_intents(state, ctx) -> None:
    from tools.testers.backtest.modules.strategy_book import apply_strategy_intent_precompute_policy

    by_policy: dict[str, list[Any]] = {}
    for strategy in ctx.active_strategies:
        config = state.config_for(strategy)
        if not config.uses_flow("signal_precomputed"):
            continue
        kind = str(config.get(TargetStrategyModule.strategy_kind, "group") or "group")
        if strategy_intent_policy_for(kind) is None:
            continue
        by_policy.setdefault(kind, []).append(strategy)
    for kind, strategies in by_policy.items():
        policy = strategy_intent_policy_for(kind)
        if policy is None:
            continue
        apply_strategy_intent_precompute_policy(state, ctx, strategies, policy)
