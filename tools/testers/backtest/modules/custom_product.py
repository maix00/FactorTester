"""CustomProductModule — unified per-product historical field overrides."""

from __future__ import annotations

from typing import Any, ClassVar

from .base import ExecutableModule, FieldDefinition, FieldRef


def custom_product_editor_definition(
    *,
    label: str,
    tab: str,
    tab_label: str,
    tab_order: int,
    module_filter: str,
    visible_when: dict[str, tuple[Any, ...]],
    chip_template: str,
    display_order: int,
) -> FieldDefinition:
    serialization = _custom_product_serialization(
        module_filter=module_filter,
        display_order=display_order,
    )
    return FieldDefinition(
        public=True,
        label=label,
        default=[],
        control_template="custom_product_overrides",
        tab=tab,
        visible_when=visible_when,
        editable_when=visible_when,
        chip_template=chip_template,
        tab_label=tab_label,
        tab_order=tab_order,
        serialization=serialization,
    )


def _custom_product_serialization(
    *,
    module_filter: str | None = None,
    display_order: int = 90,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "custom_product_overrides",
        "storage_key": "custom_product_fields",
        "display_order": display_order,
        "columns": (
            {"key": "product", "label": "产品/合约代码", "type": "text", "required": True},
            {"key": "field", "label": "字段", "type": "select", "required": True},
            {"key": "value", "label": "值", "type": "dynamic", "required": True},
            {"key": "start", "label": "开始时间", "type": "datetime", "required": False},
            {"key": "end", "label": "结束时间", "type": "datetime", "required": False},
        ),
        "fields": (
            {"value": "MarginRatio", "label": "保证金率", "unit": "ratio", "module": "margin", "value_type": "number", "allow_time_range": True},
            {"value": "OpenRatioByMoney", "label": "开仓费率", "unit": "ratio", "module": "fee", "value_type": "number", "allow_time_range": True},
            {"value": "OpenRatioByVolume", "label": "开仓固定费", "unit": "currency/lot", "module": "fee", "value_type": "number", "allow_time_range": True},
            {"value": "CloseRatioByMoney", "label": "平仓费率", "unit": "ratio", "module": "fee", "value_type": "number", "allow_time_range": True},
            {"value": "CloseRatioByVolume", "label": "平仓固定费", "unit": "currency/lot", "module": "fee", "value_type": "number", "allow_time_range": True},
            {"value": "CloseTodayRatioByMoney", "label": "平今费率", "unit": "ratio", "module": "fee", "value_type": "number", "allow_time_range": True},
            {"value": "CloseTodayRatioByVolume", "label": "平今固定费", "unit": "currency/lot", "module": "fee", "value_type": "number", "allow_time_range": True},
            {
                "value": "CostBasisMethod", "label": "成本法", "unit": "enum",
                "module": "trading_rule", "value_type": "select",
                "value_options": (
                    ("WeightAverage", "加权平均成本法"),
                    ("FIFO", "先进先出"),
                    ("LIFO", "后进先出"),
                    ("HIFO", "高进先出"),
                    ("DailyMarkToMarket", "逐日盯市"),
                ),
                "allow_time_range": False,
            },
        ),
    }
    if module_filter:
        payload["module_filter"] = module_filter
    return payload


class CustomProductModule(ExecutableModule):
    key: ClassVar[str] = "custom_product"
    label: ClassVar[str] = "自定义字段"
    order: ClassVar[int] = 175

    custom_product_fields: ClassVar[FieldRef[list[dict[str, Any]]]] = FieldRef("custom_product_fields")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "custom_product_fields": FieldDefinition(
            public=True,
            label="自定义字段",
            default=[],
            control_template="custom_product_overrides",
            tab="engine",
            visible_when={"engine_mode": ("custom",)},
            editable_when={"engine_mode": ("custom",)},
            chip_template="自定义字段: {value}",
            info_overlay={"type": "custom_product_fields"},
            tab_label="执行引擎",
            tab_order=10,
            serialization=_custom_product_serialization(),
        ),
    }


def custom_product_overrides_for(config) -> list[dict[str, Any]]:
    raw = config.get(CustomProductModule.custom_product_fields, [])
    return raw if isinstance(raw, list) else []


def apply_custom_product_fields(fields: dict[str, dict[str, object]], config, timestamp=None) -> dict[str, dict[str, object]]:
    overrides = custom_product_overrides_for(config)
    if not overrides:
        return fields
    out = {product: dict(values) for product, values in fields.items()}
    for item in overrides:
        product = str(item.get("product") or "").strip()
        field = str(item.get("field") or "").strip()
        if not product or not field:
            continue
        if timestamp is not None and not _override_active(item, timestamp):
            continue
        value = item.get("value")
        out.setdefault(product, {})[field] = value
    return out


def _override_active(item: dict[str, Any], timestamp) -> bool:
    import pandas as pd

    ts = pd.Timestamp(timestamp)
    start = item.get("start")
    end = item.get("end")
    if start not in (None, "") and ts < pd.Timestamp(start):
        return False
    if end not in (None, "") and ts > pd.Timestamp(end):
        return False
    return True
