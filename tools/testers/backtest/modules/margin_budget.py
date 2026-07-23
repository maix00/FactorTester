"""MarginBudgetModule — scales relative targets at the cash-pool boundary."""

from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.margin import MarginModule
from tools.testers.backtest.modules.target import TargetStrategyModule

from .margin_budget_impl.runtime import apply_target_margin_budget


class MarginBudgetModule(ExecutableModule):
    key: ClassVar[str] = "margin_budget"
    label: ClassVar[str] = "保证金预算"
    order: ClassVar[int] = 165

    target_margin_utilization: ClassVar[FieldRef[float]] = FieldRef("target_margin_utilization")
    max_margin_utilization: ClassVar[FieldRef[float]] = FieldRef("max_margin_utilization")
    margin_utilization_tolerance: ClassVar[FieldRef[float]] = FieldRef("margin_utilization_tolerance")
    margin_budget_summary: ClassVar[FieldRef[Any]] = FieldRef("margin_budget_summary")
    cash_pool_equity: ClassVar[FieldRef[Any]] = FieldRef("cash_pool_equity")
    target_margin: ClassVar[FieldRef[Any]] = FieldRef("target_margin")
    projected_margin: ClassVar[FieldRef[Any]] = FieldRef("projected_margin")
    weighted_margin_ratio: ClassVar[FieldRef[Any]] = FieldRef("weighted_margin_ratio")
    target_scale: ClassVar[FieldRef[Any]] = FieldRef("target_scale")
    gross_leverage: ClassVar[FieldRef[Any]] = FieldRef("gross_leverage")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "target_margin_utilization": FieldDefinition(
            public=True, label="目标保证金利用率", default=0.80, control_template="number", tab="margin",
            minimum=0.01, maximum=0.99, step=0.01,
            visible_when={"margin_mode": ("auto", "exact", "custom", "fixed")},
            chip_template="目标保证金: {value}", tab_label="保证金", tab_order=160,
        ),
        "max_margin_utilization": FieldDefinition(
            public=True, label="保证金利用率上限", default=0.85, control_template="number", tab="margin",
            minimum=0.01, maximum=0.99, step=0.01,
            visible_when={"margin_mode": ("auto", "exact", "custom", "fixed")},
            chip_template="保证金上限: {value}", tab_label="保证金", tab_order=160,
        ),
        "margin_utilization_tolerance": FieldDefinition(
            public=True, label="保证金目标容差", default=0.01, control_template="number", tab="margin",
            minimum=0.0, maximum=0.10, step=0.001,
            visible_when={"margin_mode": ("auto", "exact", "custom", "fixed")},
            chip_template="保证金容差: {value}", tab_label="保证金", tab_order=160,
        ),
        "margin_budget_summary": FieldDefinition(public=False, display_value_kind="margin_budget_table"),
        "cash_pool_equity": FieldDefinition(public=False),
        "target_margin": FieldDefinition(public=False),
        "projected_margin": FieldDefinition(public=False),
        "weighted_margin_ratio": FieldDefinition(public=False),
        "target_scale": FieldDefinition(public=False),
        "gross_leverage": FieldDefinition(public=False),
    }

    apply_target_margin_budget: ClassVar[Flow] = Flow(
        "apply_target_margin_budget",
        inputs=(
            TargetStrategyModule.trade_intent, TargetStrategyModule.target_weights,
            LedgerModule.equity, MarketDataModule.current_prices,
            MarketDataModule.current_historical_fields, MarginModule.margin_mode,
            MarginModule.fixed_margin_ratio, target_margin_utilization,
            max_margin_utilization, margin_utilization_tolerance,
        ),
        outputs=(
            TargetStrategyModule.trade_intent, TargetStrategyModule.target_weights,
            margin_budget_summary, cash_pool_equity, target_margin, projected_margin,
            weighted_margin_ratio, target_scale, gross_leverage,
        ),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=18,
        description="按现金池目标保证金利用率缩放组合",
        compute=lambda state, ctx: apply_target_margin_budget(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (apply_target_margin_budget,)
