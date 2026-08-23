"""Fee field schema and compatibility exports."""

from __future__ import annotations

from typing import ClassVar

from tools.testers.backtest.engines.native.fields import (
    ExecutableModule,
    FieldDefinition,
    FieldRef,
)
from tools.testers.backtest.modules.custom_product import (
    custom_product_editor_definition,
)
from tools.testers.backtest.modules.fee_impl.constants import (
    CUSTOM_FEE_FIELDS as _CUSTOM_FEE_FIELDS,
    FEE_FIELDS as _FEE_FIELDS,
)
from tools.testers.backtest.modules.fee_impl.flows import build_fee_flow
from tools.testers.backtest.modules.fee_impl.lot_split import (
    ordered_lots_for_close as _ordered_lots_for_close,
    split_close_today_yesterday as _split_close_today_yesterday,
    split_open_close_quantity as _split_open_close_quantity,
)
from tools.testers.backtest.modules.fee_impl.market import (
    explicit_offset_quantities as _explicit_offset_quantities,
    fee_part as _fee_part,
    has_any_fee_field as _has_any_fee_field,
    market_fee_cost as _market_fee_cost,
    requires_complete_fee_fields as _requires_complete_fee_fields,
)
from tools.testers.backtest.modules.fee_impl.mode import (
    normalise_fee_mode as _normalise_fee_mode,
    number as _number,
    resolve_fee_mode as _resolve_fee_mode,
    resolve_fee_mode_from_ledger_config as _resolve_fee_mode_from_ledger_config,
    strategy_value as _strategy_value,
)
from tools.testers.backtest.modules.fee_impl.resolution import (
    resolve_fee_cost as _resolve_fee_cost,
    resolve_fixed_fee_cost as _resolve_fixed_fee_cost,
)


class FeeModule(ExecutableModule):
    key: ClassVar[str] = "transaction_cost"
    label: ClassVar[str] = "交易费用"

    fee_mode: ClassVar[FieldRef[str]] = FieldRef("fee_mode")
    transaction_fee_source: ClassVar[FieldRef[str]] = FieldRef(
        "transaction_fee_source",
    )
    fixed_fee_rate: ClassVar[FieldRef[float]] = FieldRef("fixed_fee_rate")
    fields: ClassVar[dict[str, FieldDefinition]] = {
        "fee_mode": FieldDefinition(
            public=True, label="费用", default="auto",
            editor="select", tab="cost",
            options=(
                ("auto", "自动"), ("exact", "严格交易规则"),
                ("custom", "自定义品种/合约"), ("close_yesterday", "按平昨"),
                ("close_today", "按平今"), ("fixed", "固定费率"),
                ("zero", "不计费用"),
            ),
            editable_if={"engine_mode": ("custom",)},
            default_if={
                "engine_mode": {
                    "basic": "zero", "auto": "auto", "exact": "exact",
                },
            },
            chip_template="费用: {value}", tab_label="费用", tab_order=100,
        ),
        "transaction_fee_source": FieldDefinition(
            public=True, label="交易费来源", default="auto",
            editor="select", tab="cost",
            options=(
                ("auto", "按经纪商/市场规则自动"),
                ("exchange", "交易所"), ("openctp", "OpenCTP经纪商"),
            ),
            editable_if={"engine_mode": ("custom",)},
            default_if={
                "counterparty_profile": {
                    "exchange_base": "exchange",
                    "openctp_broker": "openctp",
                },
            },
            chip_template="交易费来源: {value}",
            tab_label="费用", tab_order=100,
        ),
        "fixed_fee_rate": FieldDefinition(
            public=True, label="固定费率", default=0.0,
            editor="number", tab="cost",
            visible_if={"fee_mode": ("fixed",)},
            chip_template="固定费率: {value}", tab_label="费用", tab_order=100,
        ),
        "fee_custom_product_fields": custom_product_editor_definition(
            label="自定义费用字段", tab="cost", tab_label="费用", tab_order=100,
            module_filter="fee",
            visible_if={"engine_mode": ("custom",), "fee_mode": ("custom",)},
            display_order=95, fields=_CUSTOM_FEE_FIELDS,
        ),
    }


FeeModule.resolve_fee_cost = build_fee_flow(FeeModule)
FeeModule.flows = (FeeModule.resolve_fee_cost,)
