"""Typed auxiliary-analysis contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .options import AnalysisOptionDefinition


class AnalysisTargetOrigin(str, Enum):
    CORE = "core"
    ANALYSIS = "analysis"


class AnalysisTargetCardinality(str, Enum):
    ONE = "one"
    MANY = "many"


class AnalysisMapping(str, Enum):
    MAP_EACH = "map_each"
    COMBINE = "combine"


@dataclass(frozen=True, slots=True)
class AnalysisParameterDefinition:
    key: str
    label: str
    control_template: str
    default: Any
    required: bool = False
    options: tuple[AnalysisOptionDefinition, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    help_text: str = ""
    serialization: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.control_template:
            raise ValueError("analysis parameter requires key, label, and template")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "control_template": self.control_template,
            "default": self.default,
            "required": self.required,
            "options": [option.to_dict() for option in self.options],
            "minimum": self.minimum,
            "maximum": self.maximum,
            "step": self.step,
            "help_text": self.help_text,
            "serialization": dict(self.serialization),
        }


@dataclass(frozen=True, slots=True)
class AnalysisInputContract:
    accepted_kinds: tuple[str, ...]
    target_origins: tuple[AnalysisTargetOrigin, ...]
    cardinality: AnalysisTargetCardinality = AnalysisTargetCardinality.ONE
    mapping: AnalysisMapping = AnalysisMapping.MAP_EACH
    minimum_targets: int = 1
    maximum_targets: int | None = 1
    same_axes: tuple[str, ...] = ()
    varying_axes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.accepted_kinds or any(not item for item in self.accepted_kinds):
            raise ValueError("analysis input contract requires accepted data kinds")
        if not self.target_origins:
            raise ValueError("analysis input contract requires target origins")
        if self.minimum_targets < 1:
            raise ValueError("analysis input minimum target count must be positive")
        if (
            self.maximum_targets is not None
            and self.maximum_targets < self.minimum_targets
        ):
            raise ValueError(
                "analysis input maximum target count is below its minimum"
            )
        if self.cardinality is AnalysisTargetCardinality.ONE and (
            self.minimum_targets != 1 or self.maximum_targets != 1
        ):
            raise ValueError("single-target analysis must accept exactly one target")
        overlap = set(self.same_axes) & set(self.varying_axes)
        if overlap:
            raise ValueError(
                "analysis input axes cannot be both fixed and varying: "
                f"{overlap}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_kinds": list(self.accepted_kinds),
            "target_origins": [item.value for item in self.target_origins],
            "cardinality": self.cardinality.value,
            "mapping": self.mapping.value,
            "minimum_targets": self.minimum_targets,
            "maximum_targets": self.maximum_targets,
            "same_axes": list(self.same_axes),
            "varying_axes": list(self.varying_axes),
        }


@dataclass(frozen=True, slots=True)
class AnalysisTypeDefinition:
    key: str
    label: str
    input_contract: AnalysisInputContract
    output_kind: str
    order: int
    help_text: str = ""
    parameters: tuple[AnalysisParameterDefinition, ...] = ()
    required_core_inputs: tuple[str, ...] = ()
    result_capabilities: tuple[str, ...] = ()
    batch_supported: bool = True

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.output_kind:
            raise ValueError("analysis type requires key, label, and output kind")
        keys = [item.key for item in self.parameters]
        if len(keys) != len(set(keys)):
            raise ValueError(f"analysis type {self.key} has duplicate parameters")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "order": self.order,
            "help_text": self.help_text,
            "input_contract": self.input_contract.to_dict(),
            "output_kind": self.output_kind,
            "parameters": [item.to_dict() for item in self.parameters],
            "required_core_inputs": list(self.required_core_inputs),
            "result_capabilities": list(self.result_capabilities),
            "batch_supported": self.batch_supported,
        }


__all__ = [
    "AnalysisInputContract",
    "AnalysisMapping",
    "AnalysisParameterDefinition",
    "AnalysisTargetCardinality",
    "AnalysisTargetOrigin",
    "AnalysisTypeDefinition",
]
