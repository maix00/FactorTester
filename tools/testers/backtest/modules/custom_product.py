"""CustomProductModule — unified per-product historical field overrides."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, ClassVar

from .base import ExecutableModule, FieldDefinition, FieldRef

_CUSTOM_PRODUCT_FIELDS: dict[str, dict[str, Any]] = {}


def custom_product_editor_definition(
    *,
    label: str,
    tab: str,
    tab_label: str,
    tab_order: int,
    module_filter: str,
    visible_when: dict[str, tuple[Any, ...]],
    display_order: int,
    fields: tuple[dict[str, Any], ...],
) -> FieldDefinition:
    register_custom_product_fields(module_filter, fields)
    serialization = _custom_product_serialization(
        module_filter=module_filter,
        display_order=display_order,
        module_editor=_module_editor_metadata(tab=tab, visible_when=visible_when),
    )
    return FieldDefinition(
        public=True,
        label=label,
        default=[],
        control_template="custom_product_overrides",
        tab=tab,
        visible_when=visible_when,
        editable_when=visible_when,
        tab_label=tab_label,
        tab_order=tab_order,
        serialization=serialization,
    )


def register_custom_product_fields(module_key: str, fields: tuple[dict[str, Any], ...]) -> None:
    if not module_key:
        raise ValueError("custom product field registration requires module_key")
    for item in fields:
        field = dict(item)
        value = str(field.get("value") or "").strip()
        if not value:
            raise ValueError(f"custom product field from {module_key!r} is missing value")
        field["module"] = module_key
        existing = _CUSTOM_PRODUCT_FIELDS.get(value)
        if existing and existing != field:
            raise ValueError(f"duplicate custom product field registration: {value}")
        _CUSTOM_PRODUCT_FIELDS[value] = field


def custom_product_field_registry(module_filter: str | None = None) -> tuple[dict[str, Any], ...]:
    fields = tuple(dict(field) for field in _CUSTOM_PRODUCT_FIELDS.values())
    if not module_filter:
        return fields
    return tuple(field for field in fields if field.get("module") == module_filter)


def refresh_custom_product_field_definitions() -> None:
    """Refresh serialization after all modules have registered their fields."""
    for key, fd in tuple(CustomProductModule.fields.items()):
        if fd.serialization and fd.serialization.get("kind") == "custom_product_overrides":
            module_filter = fd.serialization.get("module_filter")
            CustomProductModule.fields[key] = replace(
                fd,
                serialization=_custom_product_serialization(
                    module_filter=module_filter,
                    display_order=int(fd.serialization.get("display_order") or 90),
                    module_editor=fd.serialization.get("module_editor"),
                ),
            )


def _module_editor_metadata(
    *,
    tab: str,
    visible_when: dict[str, tuple[Any, ...]],
) -> dict[str, Any]:
    mode_conditions = {
        key: list(value)
        for key, value in visible_when.items()
        if key != "engine_mode"
    }
    return {"tab": tab, "mode_when": mode_conditions}


def _custom_product_serialization(
    *,
    module_filter: str | None = None,
    display_order: int = 90,
    module_editor: dict[str, Any] | None = None,
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
        "fields": custom_product_field_registry(module_filter),
    }
    if module_filter:
        payload["module_filter"] = module_filter
    if module_editor:
        payload["module_editor"] = dict(module_editor)
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
