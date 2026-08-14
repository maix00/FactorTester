"""Options shared by core axes and analysis parameters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnalysisOptionDefinition:
    value: str
    label: str

    def __post_init__(self) -> None:
        if not self.value or not self.label:
            raise ValueError("analysis option requires value and label")

    def to_dict(self) -> dict[str, str]:
        return {"value": self.value, "label": self.label}


__all__ = ["AnalysisOptionDefinition"]
