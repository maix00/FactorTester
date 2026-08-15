"""Core-test authoring and execution contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tools.testers.field_spec import ValueDescriptor


@dataclass(frozen=True, slots=True)
class CoreAxisDefinition:
    key: str
    label: str
    authoring_key: str
    value_descriptor: ValueDescriptor
    source_adapter: str = ""
    accepts_many: bool = False
    resolution_adapter: str = "identity"
    help_text: str = ""
    value_contract: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.authoring_key:
            raise ValueError("core axis requires key, label, and authoring key")
        if not self.resolution_adapter:
            raise ValueError("core axis requires a resolution adapter")
        descriptor_many = self.value_descriptor.cardinality == "many"
        if descriptor_many != self.accepts_many:
            raise ValueError(
                "core axis cardinality must match value descriptor: "
                f"{self.key} accepts_many={self.accepts_many} "
                f"descriptor={self.value_descriptor.cardinality}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "authoring_key": self.authoring_key,
            "value_descriptor": self.value_descriptor.to_dict(),
            "source_adapter": self.source_adapter,
            "accepts_many": self.accepts_many,
            "resolution_adapter": self.resolution_adapter,
            "help_text": self.help_text,
            "value_contract": dict(self.value_contract),
        }


@dataclass(frozen=True, slots=True)
class CoreTestDefinition:
    label: str
    axes: tuple[str, ...]
    output_kinds: tuple[str, ...]
    axis_definitions: tuple[CoreAxisDefinition, ...] = ()
    add_flow_label: str = "新增核心测试"
    batch_add_flow_label: str = "批量新增核心测试"

    def __post_init__(self) -> None:
        if not self.label or not self.axes or not self.output_kinds:
            raise ValueError("core test definition requires label, axes, and outputs")
        keys = tuple(item.key for item in self.axis_definitions)
        if keys and keys != self.axes:
            raise ValueError(
                "core axis definitions must exactly match the declared axes"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "axes": list(self.axes),
            "output_kinds": list(self.output_kinds),
            "axis_definitions": [item.to_dict() for item in self.axis_definitions],
            "add_flow_label": self.add_flow_label,
            "batch_add_flow_label": self.batch_add_flow_label,
        }


__all__ = ["CoreAxisDefinition", "CoreTestDefinition"]
