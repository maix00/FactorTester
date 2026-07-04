"""MarginModule — margin rule settings shared by native position accounting.

Margin is deliberately independent from TradingRuleModule: engine mode chooses
the broad rule strictness, while margin mode chooses how much equity a position
occupies.
"""

from __future__ import annotations

from typing import ClassVar

from .base import ExecutableModule, FieldDefinition, FieldRef
from .custom_product import custom_product_editor_definition
from .engine import engine_mode_for

_CUSTOM_MARGIN_FIELDS = (
    {
        "value": "LongMarginRatioByMoney",
        "label": "多头保证金率",
        "unit": "ratio",
        "value_type": "number",
        "allow_time_range": True,
    },
    {
        "value": "ShortMarginRatioByMoney",
        "label": "空头保证金率",
        "unit": "ratio",
        "value_type": "number",
        "allow_time_range": True,
    },
    {
        "value": "LongMarginRatioByVolume",
        "label": "多头每手保证金",
        "unit": "currency/lot",
        "value_type": "number",
        "allow_time_range": True,
    },
    {
        "value": "ShortMarginRatioByVolume",
        "label": "空头每手保证金",
        "unit": "currency/lot",
        "value_type": "number",
        "allow_time_range": True,
    },
)


class MarginModule(ExecutableModule):
    key: ClassVar[str] = "margin"
    label: ClassVar[str] = "保证金"

    margin_mode: ClassVar[FieldRef[str]] = FieldRef("margin_mode")
    fixed_margin_ratio: ClassVar[FieldRef[float]] = FieldRef("fixed_margin_ratio")
    collateral_fraction: ClassVar[FieldRef[float]] = FieldRef("collateral_fraction")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "margin_mode": FieldDefinition(
            public=True, label="保证金", default="auto", control_template="select", tab="margin",
            options=(
                ("auto", "按市场规则自动"),
                ("exact", "严格历史规则"),
                ("custom", "自定义品种/合约"),
                ("fixed", "固定比例"),
                ("none", "关闭"),
            ),
            editable_when={"engine_mode": ("custom",)},
            default_when={"engine_mode": {"basic": "none", "auto": "auto", "exact": "exact"}},
            chip_template="保证金: {value}", tab_label="保证金", tab_order=160,
        ),
        "fixed_margin_ratio": FieldDefinition(
            public=True, label="保证金率", default=1.0, control_template="number", tab="margin",
            visible_when={"margin_mode": ("fixed",)},
            chip_template="保证金率: {value}", tab_label="保证金", tab_order=160,
        ),
        "collateral_fraction": FieldDefinition(
            public=True, label="抵押比例", default=1.0, control_template="number", tab="margin",
            visible_when={"margin_mode": ("fixed", "auto", "exact", "custom")},
            chip_template="抵押比例: {value}", tab_label="保证金", tab_order=160,
        ),
        "margin_custom_product_fields": custom_product_editor_definition(
            label="自定义保证金字段",
            tab="margin",
            tab_label="保证金",
            tab_order=160,
            module_filter="margin",
            visible_when={"engine_mode": ("custom",), "margin_mode": ("custom",)},
            display_order=95,
            fields=_CUSTOM_MARGIN_FIELDS,
        ),
    }


def _resolve_margin_mode(strategy_config, ledger_config=None) -> str:
    engine_mode = engine_mode_for(strategy_config)
    if engine_mode == "basic":
        return "none"
    if engine_mode == "auto":
        return "auto"
    if engine_mode == "exact":
        return "exact"
    return str(getattr(ledger_config, "margin_mode", None) or "auto")


def _resolve_margin_mode_from_ledger_config(ledger_config=None) -> str:
    return str(getattr(ledger_config, "margin_mode", None) or "auto")


def _resolve_margin_ratio(strategy_config, market_margin_ratio: float | None, ledger_config=None) -> float:
    mode = _resolve_margin_mode(strategy_config, ledger_config)
    if mode == "none":
        return 0.0
    if mode == "fixed":
        return float(getattr(ledger_config, "fixed_margin_ratio", None) or 1.0)
    if mode == "exact" and market_margin_ratio is None:
        raise KeyError("exact margin mode requires historical long/short margin fields")
    return float(market_margin_ratio or 0.0)


def _resolve_margin_ratio_from_ledger_config(market_margin_ratio: float | None, ledger_config=None) -> float:
    mode = _resolve_margin_mode_from_ledger_config(ledger_config)
    if mode == "none":
        return 0.0
    if mode == "fixed":
        return float(getattr(ledger_config, "fixed_margin_ratio", None) or 1.0)
    if mode == "exact" and market_margin_ratio is None:
        raise KeyError("exact margin mode requires historical long/short margin fields")
    return float(market_margin_ratio or 0.0)
