"""Common strategy intent state.

Concrete strategy modules such as group membership, long-short composition, or
technical rules produce trade intents in different ways. Target weights are one
intent representation, not the universal strategy abstraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.policies.registry import (
    generate_strategy_intents as _generate_strategy_intents,
    precompute_strategy_intents as _precompute_strategy_intents,
    register_strategy_intent_policy,
    strategy_intent_policy_for,
)

_SIGNAL_VALUE_REF: FieldRef[Any] = FieldRef("signal_value", owner="FactorSignalModule")
_CURRENT_PRICES_REF: FieldRef[Any] = FieldRef("current_prices", owner="MarketDataModule")
_CURRENT_HISTORICAL_FIELDS_REF: FieldRef[Any] = FieldRef("current_historical_fields", owner="MarketDataModule")
_CAUSAL_VALUATION_TABLE_REF: FieldRef[Any] = FieldRef("causal_valuation_table", owner="MarketDataModule")
_POSITION_POLICY_REF: FieldRef[str] = FieldRef("position_policy", owner="GroupMembershipModule")
_REBALANCE_TRIGGER_REF: FieldRef[str] = FieldRef("rebalance_trigger", owner="GroupMembershipModule")
_SPLIT_COUNT_REF: FieldRef[int] = FieldRef("split_count", owner="GroupMembershipModule")
_GROUP_INDEX_REF: FieldRef[int] = FieldRef("group_index", owner="GroupMembershipModule")
_ALLOCATION_POLICY_REF: FieldRef[str] = FieldRef("allocation_policy", owner="GroupMembershipModule")
_VOLATILITY_LOOKBACK_REF: FieldRef[Any] = FieldRef("volatility_lookback", owner="GroupMembershipModule")
_VOLATILITY_WARMUP_REF: FieldRef[int] = FieldRef("volatility_warmup", owner="GroupMembershipModule")
_PRODUCT_MASK_NAMES_REF: FieldRef[Any] = FieldRef("product_mask_names", owner="GroupMembershipModule")
_SCREEN_RULE_REF: FieldRef[str] = FieldRef("screen_rule", owner="GroupMembershipModule")
_SCREEN_LOWER_REF: FieldRef[float] = FieldRef("screen_lower", owner="GroupMembershipModule")
_SCREEN_UPPER_REF: FieldRef[float] = FieldRef("screen_upper", owner="GroupMembershipModule")
_SIZING_TRANSFORM_REF: FieldRef[str] = FieldRef("sizing_transform", owner="GroupMembershipModule")


@dataclass(frozen=True)
class TargetWeightIntent:
    weights: dict[Any, float]
    reason: str = "target_weights"


@dataclass(frozen=True)
class PairedTargetWeightIntent(TargetWeightIntent):
    """One strategy decision whose products are economically linked legs."""

    parent_intent_id: str = ""
    execution_policy: str = "synchronized_submit"


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
    strategy_intent_mode: ClassVar[FieldRef[str]] = strategy_kind

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "strategy_intent_mode": FieldDefinition(
            public=True,
            label="策略意图",
            default="group",
            control_template="select",
            tab="group_strategy",
            options=(
                ("group", "分组"),
                ("threshold", "阈值"),
                ("term_carry", "Term Carry"),
                ("custom", "自定义事件"),
            ),
            chip_template="策略意图: {value}",
            tab_label="分组数量",
            tab_order=90,
        ),
        "trade_intent": FieldDefinition(public=False, display_value_kind="trade_intent"),
    }

    precompute_strategy_intents: ClassVar[Flow] = Flow(
        "precompute_strategy_intents",
        inputs=(
            strategy_kind,
            _SIGNAL_VALUE_REF,
            _CURRENT_PRICES_REF,
            _CURRENT_HISTORICAL_FIELDS_REF,
            _CAUSAL_VALUATION_TABLE_REF,
            _POSITION_POLICY_REF,
            _REBALANCE_TRIGGER_REF,
            _SPLIT_COUNT_REF,
            _GROUP_INDEX_REF,
            _ALLOCATION_POLICY_REF,
            _VOLATILITY_LOOKBACK_REF,
            _VOLATILITY_WARMUP_REF,
            _PRODUCT_MASK_NAMES_REF,
            _SCREEN_RULE_REF,
            _SCREEN_LOWER_REF,
            _SCREEN_UPPER_REF,
            _SIZING_TRANSFORM_REF,
        ),
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
    retention_mode: str = "full"
    strategy_established_target_weights: dict[Any, Any] = field(default_factory=dict)
    strategy_selection_cache: dict[Any, Any] = field(default_factory=dict)
    target_trace: dict[Any, dict[str, Any]] = field(default_factory=dict)
    rolling_volatility_tables: dict[tuple[int, int], Any] = field(default_factory=dict)
    rolling_volatility_locators: dict[tuple[int, int], Any] = field(default_factory=dict)
    precomputed_target_intents: dict[Any, dict[Any, TargetWeightIntent]] = field(default_factory=dict)
    execution_schedule_cache: dict[Any, Any] = field(default_factory=dict)
    effective_lot_size_cache: dict[tuple[Any, Any], float | None] = field(default_factory=dict)
    strategy_product_ledger_cache: dict[tuple[Any, Any, Any], Any] = field(default_factory=dict)
    static_strategy_product_ledger_cache: dict[tuple[Any, Any], Any] = field(default_factory=dict)
    # Keep the object-key caches above for compatibility and diagnostics, but
    # use identity keys in the hot replay path.  The tuple retains both
    # objects, making the fast path safe even if Python later reuses an id.
    static_strategy_product_ledger_identity_cache: dict[
        tuple[int, int], tuple[Any, Any, Any]
    ] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.retention_mode not in {"summary", "full"}:
            raise ValueError("target retention_mode must be 'summary' or 'full'")

    def record_target_trace(self, strategy: Any, timestamp: Any, weights: dict[Any, Any]) -> None:
        if timestamp is None:
            return
        if self.retention_mode == "summary":
            trace = self.target_trace.setdefault(strategy, TargetTraceDigest())
            trace.record(timestamp, weights)
            return
        self.target_trace.setdefault(strategy, {})[timestamp.isoformat()] = {
            str(product): weight for product, weight in weights.items()
        }

    def target_trace_for(self, strategy: Any) -> Any:
        trace = self.target_trace.get(strategy, {})
        if isinstance(trace, TargetTraceDigest):
            return trace
        return dict(trace)


class TargetTraceDigest:
    """Streaming target-trace identity used by summary result projections.

    Signal timestamps are dispatched monotonically and one target is recorded
    per strategy/timestamp.  The digest follows the same row framing as the
    full trace checksum, without retaining every product-weight mapping.
    """

    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self._count = 0
        self._last_timestamp = ""

    def record(self, timestamp: Any, weights: dict[Any, Any]) -> None:
        timestamp_text = timestamp.isoformat()
        payload = {str(product): weight for product, weight in weights.items()}
        row = {"timestamp": timestamp_text, "payload": payload}
        self._digest.update(timestamp_text.encode("utf-8"))
        self._digest.update(b"\0")
        self._digest.update(json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8"))
        self._digest.update(b"\n")
        self._count += 1
        self._last_timestamp = timestamp_text

    def __len__(self) -> int:
        return self._count

    def __bool__(self) -> bool:
        return self._count > 0

    def checksum(self) -> str | None:
        return self._digest.hexdigest() if self._count else None
