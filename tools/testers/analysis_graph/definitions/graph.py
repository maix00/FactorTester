"""Top-level typed analysis graph definition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .analysis import AnalysisTypeDefinition
from .core import CoreTestDefinition


@dataclass(frozen=True, slots=True)
class AnalysisGraphDefinition:
    key: str
    label: str
    core_test: CoreTestDefinition
    analysis_types: tuple[AnalysisTypeDefinition, ...]
    projection: str = "tree"
    authoritative_model: str = "dag"
    overlay_modes: tuple[str, ...] = ("core_test", "auxiliary_analysis")
    authoring_contract: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.label:
            raise ValueError("analysis graph definition requires key and label")
        keys = [item.key for item in self.analysis_types]
        if len(keys) != len(set(keys)):
            raise ValueError("analysis graph contains duplicate analysis types")
        if self.authoring_contract is not None and not self.authoring_contract:
            raise ValueError("analysis graph authoring contract cannot be empty")

    def type_by_key(self, key: str) -> AnalysisTypeDefinition:
        for item in self.analysis_types:
            if item.key == key:
                return item
        raise KeyError(f"unknown analysis type: {key}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "projection": self.projection,
            "authoritative_model": self.authoritative_model,
            "overlay_modes": list(self.overlay_modes),
            "authoring_contract": dict(self.authoring_contract or {}),
            "core_test": self.core_test.to_dict(),
            "analysis_types": [
                item.to_dict()
                for item in sorted(
                    self.analysis_types,
                    key=lambda value: value.order,
                )
            ],
        }


__all__ = ["AnalysisGraphDefinition"]
