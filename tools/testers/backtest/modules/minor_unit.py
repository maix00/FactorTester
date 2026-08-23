"""MinorUnitModule — whether DataMoney amounts in this run are tracked in
integer minor units (cents) or major-unit floats."""

from __future__ import annotations

from typing import ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef


class MinorUnitModule(ExecutableModule):
    key: ClassVar[str] = "minor_unit"
    label: ClassVar[str] = "最小货币单位"

    use_minor_units: ClassVar[FieldRef[str]] = FieldRef("use_minor_units")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "use_minor_units": FieldDefinition(
            public=True, label="最小货币单位", default="auto", editor="select", tab="capital",
            options=(
                ("auto", "按执行引擎自动"),
                ("true", "使用最小货币单位"),
                ("false", "使用主要货币单位"),
            ),
            editable_if={"engine_mode": ("custom",)},
            default_if={"engine_mode": {"basic": "false"}},
            chip_template="最小货币单位: {value}", tab_label="资金", tab_order=50,
        ),
    }


def resolve_use_minor_units(strategy_config) -> bool:
    """Resolve the tri-state field before a ledger is materialized."""
    value = strategy_config.get(MinorUnitModule.use_minor_units, "auto")
    if isinstance(value, bool):
        return value
    text = str(value or "auto").strip().lower()
    if text in {"", "auto", "automatic", "true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"invalid use_minor_units value: {value!r}")
