"""MinorUnitModule — whether DataMoney amounts in this run are tracked in
integer minor units (cents) or major-unit floats."""

from __future__ import annotations

from typing import ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef


class MinorUnitModule(ExecutableModule):
    key: ClassVar[str] = "minor_unit"
    label: ClassVar[str] = "最小货币单位"

    use_minor_units: ClassVar[FieldRef[bool]] = FieldRef("use_minor_units")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "use_minor_units": FieldDefinition(
            public=True, label="最小货币单位", default=True, control_template="boolean", tab="capital",
            editable_when={"engine_mode": ("custom",)},
            default_when={"engine_mode": {"basic": False}},
            chip_template="最小货币单位: {value}", tab_label="资金", tab_order=50,
        ),
    }
