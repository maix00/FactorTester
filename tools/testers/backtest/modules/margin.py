"""MarginModule — margin rule settings shared by native position accounting.

Margin is deliberately independent from TradingRuleModule: accounting mode
chooses cost-basis and quantity bookkeeping, while margin mode chooses how much
equity a position occupies.
"""

from __future__ import annotations

from typing import ClassVar

from .base import ExecutableModule, FieldDefinition, FieldRef


class MarginModule(ExecutableModule):
    key: ClassVar[str] = "margin"
    label: ClassVar[str] = "保证金"

    margin_mode: ClassVar[FieldRef[str]] = FieldRef("margin_mode")
    fixed_margin_ratio: ClassVar[FieldRef[float]] = FieldRef("fixed_margin_ratio")
    collateral_fraction: ClassVar[FieldRef[float]] = FieldRef("collateral_fraction")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "margin_mode": FieldDefinition(
            public=True, default="auto", control_template="select", tab="margin",
            options=(("auto", "按市场规则自动"), ("fixed", "固定比例"), ("none", "关闭")),
            chip_template="保证金: {value}", tab_label="保证金", tab_order=160,
        ),
        "fixed_margin_ratio": FieldDefinition(
            public=True, default=1.0, control_template="number", tab="margin",
            visible_when={"margin_mode": ("fixed",)},
            chip_template="保证金率: {value}", tab_label="保证金", tab_order=160,
        ),
        "collateral_fraction": FieldDefinition(
            public=True, default=1.0, control_template="number", tab="margin",
            visible_when={"margin_mode": ("fixed", "auto")},
            chip_template="抵押比例: {value}", tab_label="保证金", tab_order=160,
        ),
    }


def _resolve_margin_mode(strategy_config) -> str:
    from .trading_rule import TradingRuleModule

    if strategy_config.get(TradingRuleModule.accounting_mode, "Basic") == "Basic":
        return "none"
    return str(strategy_config.get(MarginModule.margin_mode, "auto") or "auto")


def _resolve_margin_ratio(strategy_config, market_margin_ratio: float) -> float:
    mode = _resolve_margin_mode(strategy_config)
    if mode == "none":
        return 0.0
    if mode == "fixed":
        return strategy_config.get(MarginModule.fixed_margin_ratio, 1.0)
    return market_margin_ratio
