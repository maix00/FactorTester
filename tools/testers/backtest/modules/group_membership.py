"""Compatibility facade and Flow declaration for group strategy intent."""

from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_construct import OrderConstructModule
from tools.testers.backtest.modules.order_execution import OrderExecutionModule
from tools.testers.backtest.modules.target import (
    TargetStrategyModule,
    _generate_strategy_intents,
    register_strategy_intent_policy,
)
from tools.testers.backtest.modules.group.allocation import (
    allocate_weights as _allocate_weights,
    rolling_volatility_table as _rolling_volatility_table,
)
from tools.testers.backtest.modules.group.execution import (
    resolve_execution_schedule as _resolve_execution_schedule,
    resolve_execution_timestamp as _resolve_execution_timestamp,
    schedule_order_execution as _schedule_order_execution,
)
from tools.testers.backtest.modules.group.policy import GroupMembershipIntentPolicy
from tools.testers.backtest.modules.group.precompute.coordinator import (
    precompute_group_target_intents as _precompute_group_membership_target_intents,
)
from tools.testers.backtest.modules.group.precompute.vectorized import (
    can_vectorize as _can_vectorize_group_precompute,
    precompute_vectorized as _precompute_group_membership_target_intents_vectorized,
)
from tools.testers.backtest.modules.group.runtime import (
    group_quantile_membership as _group_quantile_membership,
    record_target_trace as _record_target_trace,
    target_trace_for,
)
from tools.testers.backtest.modules.group.selection import (
    compute_group_target_weights as _compute_group_target_weights,
    product_name as _product_name,
    tradable_signal_values as _tradable_signal_values,
)
from tools.testers.backtest.modules.group.settings import group_policy_fields


class GroupMembershipModule(TargetStrategyModule):
    key: ClassVar[str] = "group_strategy"
    label: ClassVar[str] = "分组隶属"

    split_count: ClassVar[FieldRef[int]] = FieldRef("split_count")
    group_index: ClassVar[FieldRef[int]] = FieldRef("group_index")
    target_weights: ClassVar[FieldRef[Any]] = TargetStrategyModule.target_weights
    execution_timing: ClassVar[FieldRef[str]] = FieldRef("execution_timing")
    execution_delay_bars: ClassVar[FieldRef[int]] = FieldRef("execution_delay_bars")
    dispatched_order_events: ClassVar[FieldRef[Any]] = FieldRef("dispatched_order_events")
    position_policy: ClassVar[FieldRef[str]] = FieldRef("position_policy")
    rebalance_trigger: ClassVar[FieldRef[str]] = FieldRef("rebalance_trigger")
    allocation_policy: ClassVar[FieldRef[str]] = FieldRef("allocation_policy")
    volatility_lookback: ClassVar[FieldRef[int]] = FieldRef("volatility_lookback")
    volatility_warmup: ClassVar[FieldRef[str]] = FieldRef("volatility_warmup")
    product_mask_names: ClassVar[FieldRef[Any]] = FieldRef("product_mask_names")
    screen_rule: ClassVar[FieldRef[str]] = FieldRef("screen_rule")
    screen_lower: ClassVar[FieldRef[float]] = FieldRef("screen_lower")
    screen_upper: ClassVar[FieldRef[float]] = FieldRef("screen_upper")
    sizing_transform: ClassVar[FieldRef[str]] = FieldRef("sizing_transform")

    fields = group_policy_fields()

    group_quantile_membership: ClassVar[Flow] = Flow(
        "group_quantile_membership",
        inputs=(
            FactorSignalModule.signal_value, split_count, group_index,
            FactorModule.factor_role_values,
            MarketDataModule.current_historical_fields,
            MarketDataModule.current_prices,
            MarketDataModule.current_tradable_status,
            position_policy, rebalance_trigger, allocation_policy,
            volatility_lookback, volatility_warmup, product_mask_names,
            screen_rule, screen_lower, screen_upper, sizing_transform,
        ),
        outputs=(target_weights, TargetStrategyModule.trade_intent),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL,
        description="计算分组隶属",
        order=10,
        compute=lambda state, ctx: _generate_strategy_intents(
            state, ctx, expected_kind="group",
        ),
    )
    schedule_order_execution: ClassVar[Flow] = Flow(
        "schedule_order_execution",
        inputs=(
            OrderConstructModule.orders, execution_timing, execution_delay_bars,
            OrderExecutionModule.execution_price_basis,
            EngineModule.engine_mode, EngineModule.bar_open_visibility_delay,
            MarketDataModule.required_frequency, MarketDataModule.price_tables,
        ),
        outputs=(dispatched_order_events,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL,
        order=40,
        after=(OrderConstructModule.construct_orders,),
        description="登记订单执行事件",
        compute=lambda state, ctx: _schedule_order_execution(state, ctx),
    )
    flows: ClassVar[tuple[Flow, ...]] = (
        group_quantile_membership,
        schedule_order_execution,
    )


register_strategy_intent_policy("group", GroupMembershipIntentPolicy())
