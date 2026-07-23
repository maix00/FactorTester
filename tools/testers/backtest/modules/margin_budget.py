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
from tools.testers.backtest.modules.fee import FeeModule
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.order_construct import OrderConstructModule
from tools.testers.backtest.modules.trading_rule import TradingRuleModule

from .margin_budget_impl.runtime import apply_target_margin_budget
from .margin_budget_impl.execution import enforce_execution_margin_limit


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
    execution_margin_summary: ClassVar[FieldRef[Any]] = FieldRef("execution_margin_summary")
    rounding_error: ClassVar[FieldRef[Any]] = FieldRef("rounding_error")
    hard_limit_headroom: ClassVar[FieldRef[Any]] = FieldRef("hard_limit_headroom")

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
        "execution_margin_summary": FieldDefinition(public=False, display_value_kind="margin_budget_table"),
        "rounding_error": FieldDefinition(public=False),
        "hard_limit_headroom": FieldDefinition(public=False),
    }

    apply_target_margin_budget: ClassVar[Flow] = Flow(
        "apply_target_margin_budget",
        inputs=(
            TargetStrategyModule.trade_intent, TargetStrategyModule.target_weights,
            LedgerModule.equity, MarketDataModule.current_prices,
            MarketDataModule.current_historical_fields, EngineModule.engine_mode,
            MarginModule.margin_mode,
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

    constrain_execution_margin_utilization: ClassVar[Flow] = Flow(
        "constrain_execution_margin_utilization",
        inputs=(
            MarketDataModule.current_prices, MarketDataModule.current_market_snapshot,
            MarketDataModule.current_historical_fields, EngineModule.engine_mode,
            MarginModule.margin_mode, MarginModule.fixed_margin_ratio,
            target_margin_utilization, max_margin_utilization,
            margin_utilization_tolerance, FeeModule.fee_mode,
            FeeModule.fixed_fee_rate, TradingRuleModule.accounting_mode,
            TradingRuleModule.cost_basis_method,
            TradingRuleModule.daily_mark_to_market_enabled,
            TradingRuleModule.use_int_position,
            OrderConstructModule.quantity_rounding_policy,
        ),
        outputs=(
            execution_margin_summary, cash_pool_equity, projected_margin,
            gross_leverage, rounding_error, hard_limit_headroom,
        ),
        phase=Phase.PER_EVENT, event_kind=EventKind.ORDER, order=10,
        description="按现金池保证金利用率硬上限调整增仓",
        event_payload_inputs=("order",),
        compute=lambda state, ctx: enforce_execution_margin_limit(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (
        apply_target_margin_budget,
        constrain_execution_margin_utilization,
    )
