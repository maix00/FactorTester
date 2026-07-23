"""ThresholdSignalModule -- non-group signal-to-target implementation."""

from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.group_membership import GroupMembershipModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.target import (
    TargetStrategyModule,
    _generate_strategy_intents,
    register_strategy_intent_policy,
)


class ThresholdSignalModule(TargetStrategyModule):
    key: ClassVar[str] = "threshold_signal"
    label: ClassVar[str] = "阈值信号"

    threshold_mode: ClassVar[FieldRef[str]] = FieldRef("threshold_mode")
    entry_threshold: ClassVar[FieldRef[float]] = FieldRef("entry_threshold")
    exit_threshold: ClassVar[FieldRef[float]] = FieldRef("exit_threshold")
    quantile_entry: ClassVar[FieldRef[float]] = FieldRef("quantile_entry")
    quantile_exit: ClassVar[FieldRef[float]] = FieldRef("quantile_exit")
    side_mode: ClassVar[FieldRef[str]] = FieldRef("side_mode")
    target_weights: ClassVar[FieldRef[Any]] = TargetStrategyModule.target_weights

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "threshold_mode": FieldDefinition(
            public=True,
            label="阈值模式",
            default="absolute",
            control_template="select",
            tab="group_strategy",
            options=(("absolute", "绝对阈值"), ("cross_section_quantile", "截面分位")),
            chip_template="阈值模式: {value}",
            tab_label="分组数量",
            tab_order=90,
            visible_when={"strategy_intent_mode": ("threshold",)},
        ),
        "entry_threshold": FieldDefinition(
            public=True,
            label="入场阈值",
            default=0.0,
            control_template="number",
            tab="group_strategy",
            chip_template="入场阈值: {value}",
            tab_label="分组数量",
            tab_order=90,
            visible_when={"strategy_intent_mode": ("threshold",), "threshold_mode": ("absolute",)},
        ),
        "exit_threshold": FieldDefinition(
            public=True,
            label="退出阈值",
            default=0.0,
            control_template="number",
            tab="group_strategy",
            chip_template="退出阈值: {value}",
            tab_label="分组数量",
            tab_order=90,
            visible_when={"strategy_intent_mode": ("threshold",), "threshold_mode": ("absolute",)},
        ),
        "quantile_entry": FieldDefinition(
            public=True,
            label="入场分位",
            default=0.8,
            control_template="number",
            tab="group_strategy",
            minimum=0.0,
            maximum=1.0,
            step=0.01,
            chip_template="入场分位: {value}",
            tab_label="分组数量",
            tab_order=90,
            visible_when={"strategy_intent_mode": ("threshold",), "threshold_mode": ("cross_section_quantile",)},
        ),
        "quantile_exit": FieldDefinition(
            public=True,
            label="退出分位",
            default=0.6,
            control_template="number",
            tab="group_strategy",
            minimum=0.0,
            maximum=1.0,
            step=0.01,
            chip_template="退出分位: {value}",
            tab_label="分组数量",
            tab_order=90,
            visible_when={"strategy_intent_mode": ("threshold",), "threshold_mode": ("cross_section_quantile",)},
        ),
        "side_mode": FieldDefinition(
            public=True,
            label="方向",
            default="long_only",
            control_template="select",
            tab="group_strategy",
            options=(
                ("long_only", "只做多"),
                ("short_only", "只做空"),
                ("long_short_spread", "多空价差"),
            ),
            chip_template="方向: {value}",
            tab_label="分组数量",
            tab_order=90,
            visible_when={"strategy_intent_mode": ("threshold",)},
        ),
    }

    threshold_signal_target: ClassVar[Flow] = Flow(
        "threshold_signal_target",
        inputs=(
            TargetStrategyModule.strategy_kind,
            FactorSignalModule.signal_value,
            FactorModule.factor_role_values,
            MarketDataModule.current_prices,
            MarketDataModule.current_tradable_status,
            threshold_mode,
            entry_threshold,
            exit_threshold,
            quantile_entry,
            quantile_exit,
            side_mode,
            GroupMembershipModule.allocation_policy,
            GroupMembershipModule.volatility_lookback,
            GroupMembershipModule.volatility_warmup,
        ),
        outputs=(target_weights, TargetStrategyModule.trade_intent),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL,
        description="计算阈值信号目标",
        order=10,
        compute=lambda state, ctx: _generate_strategy_intents(state, ctx, expected_kind="threshold"),
    )

    flows: ClassVar[tuple[Flow, ...]] = (threshold_signal_target,)


from tools.testers.backtest.policies.threshold import (
    ThresholdSignalIntentPolicy,
    precompute_threshold_target_intents as _precompute_threshold_target_intents,
    threshold_signal_target as _threshold_signal_target,
)

register_strategy_intent_policy("threshold", ThresholdSignalIntentPolicy())
