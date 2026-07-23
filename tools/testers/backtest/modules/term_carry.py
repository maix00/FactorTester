from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import (
    FieldDefinition,
    FieldRef,
)
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.target import TargetStrategyModule

from .term_carry_runtime import build_term_carry_targets


class TermCarryStrategyModule(TargetStrategyModule):
    key: ClassVar[str] = "term_carry_strategy"
    label: ClassVar[str] = "Term Carry"

    _signal_value_ref: ClassVar[FieldRef[Any]] = FactorSignalModule.signal_value
    term_carry_near_rank: ClassVar[FieldRef[int]] = FieldRef(
        "term_carry_near_rank",
    )
    term_carry_far_rank: ClassVar[FieldRef[int]] = FieldRef(
        "term_carry_far_rank",
    )
    term_carry_entry_threshold: ClassVar[FieldRef[float]] = FieldRef(
        "term_carry_entry_threshold",
    )
    term_carry_exit_threshold: ClassVar[FieldRef[float]] = FieldRef(
        "term_carry_exit_threshold",
    )
    term_carry_gross_weight: ClassVar[FieldRef[float]] = FieldRef(
        "term_carry_gross_weight",
    )
    term_carry_diagnostics: ClassVar[FieldRef[Any]] = FieldRef(
        "term_carry_diagnostics",
    )

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "term_carry_near_rank": FieldDefinition(
            public=True, label="近月排名", default=0,
            control_template="number", minimum=0,
            visible_when={"strategy_intent_mode": ("term_carry",)},
        ),
        "term_carry_far_rank": FieldDefinition(
            public=True, label="远月排名", default=1,
            control_template="number", minimum=1,
            visible_when={"strategy_intent_mode": ("term_carry",)},
        ),
        "term_carry_entry_threshold": FieldDefinition(
            public=True, label="Carry入场阈值", default=0.05,
            control_template="number",
            visible_when={"strategy_intent_mode": ("term_carry",)},
        ),
        "term_carry_exit_threshold": FieldDefinition(
            public=True, label="Carry退出阈值", default=0.01,
            control_template="number", minimum=0.0,
            visible_when={"strategy_intent_mode": ("term_carry",)},
        ),
        "term_carry_gross_weight": FieldDefinition(
            public=True, label="价差总权重", default=1.0,
            control_template="number", minimum=0.0, maximum=1.0,
            visible_when={"strategy_intent_mode": ("term_carry",)},
        ),
        "term_carry_diagnostics": FieldDefinition(
            public=False,
        ),
    }

    term_carry_target: ClassVar[Flow] = Flow(
        "term_carry_target",
        inputs=(
            TargetStrategyModule.strategy_kind,
            FactorSignalModule.signal_value,
            ProductSelectionModule.products,
            MarketDataModule.current_prices,
            MarketDataModule.current_tradable_status,
            MarketDataModule.trading_day_resolver,
            term_carry_near_rank,
            term_carry_far_rank,
            term_carry_entry_threshold,
            term_carry_exit_threshold,
            term_carry_gross_weight,
        ),
        outputs=(
            TargetStrategyModule.target_weights,
            TargetStrategyModule.trade_intent,
            term_carry_diagnostics,
        ),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL,
        order=10,
        description="生成跨期双腿目标",
        compute=lambda state, ctx: build_term_carry_targets(
            state, ctx, TermCarryStrategyModule,
        ),
    )

    flows: ClassVar[tuple[Flow, ...]] = (term_carry_target,)
