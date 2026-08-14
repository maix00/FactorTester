"""Typed auxiliary-analysis contracts."""

from __future__ import annotations

import re
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
class AnalysisChipDefinition:
    """Backend-owned compact descriptor for an attached-analysis chip.

    This is deliberately a semantic descriptor rather than a web component
    contract.  A client may choose its visual treatment, but it must obtain
    the label, value template, source parameters and destination from the
    analysis manifest instead of keeping an analysis-name switch in code.
    """

    key: str
    label: str
    template: str
    parameter_keys: tuple[str, ...] = ()
    category: str = "analysis"
    source: str = "analysis_parameters"
    target: str = "analysis_overlay"
    clickable: bool = True
    order: int = 100

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.template:
            raise ValueError("analysis chip requires key, label, and template")
        if self.category != "analysis":
            raise ValueError("analysis chip category must be analysis")
        if self.source != "analysis_parameters":
            raise ValueError("analysis chip source must be analysis_parameters")
        if self.target != "analysis_overlay":
            raise ValueError("analysis chip target must be analysis_overlay")
        if self.order < 0:
            raise ValueError("analysis chip order must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "category": self.category,
            "template": self.template,
            "parameter_keys": list(self.parameter_keys),
            "source": self.source,
            "target": self.target,
            "clickable": self.clickable,
            "order": self.order,
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
    chip: AnalysisChipDefinition | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.output_kind:
            raise ValueError("analysis type requires key, label, and output kind")
        keys = [item.key for item in self.parameters]
        if len(keys) != len(set(keys)):
            raise ValueError(f"analysis type {self.key} has duplicate parameters")
        if self.chip is not None:
            if self.chip.key != self.key:
                raise ValueError(
                    f"analysis type {self.key} chip key must match analysis key"
                )
            parameter_keys = set(keys)
            unknown = set(self.chip.parameter_keys) - parameter_keys
            if unknown:
                raise ValueError(
                    f"analysis type {self.key} chip references unknown parameters: "
                    f"{sorted(unknown)}"
                )
            placeholders = set(re.findall(r"\{([^{}]+)\}", self.chip.template))
            if placeholders - parameter_keys:
                raise ValueError(
                    f"analysis type {self.key} chip template references unknown "
                    f"parameters: {sorted(placeholders - parameter_keys)}"
                )

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
            "chip": self.chip.to_dict() if self.chip is not None else None,
        }


__all__ = [
    "AnalysisInputContract",
    "AnalysisChipDefinition",
    "AnalysisMapping",
    "AnalysisParameterDefinition",
    "AnalysisTargetCardinality",
    "AnalysisTargetOrigin",
    "AnalysisTypeDefinition",
]
