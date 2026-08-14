"""One typed request to attach an auxiliary analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .normalization import required_texts


@dataclass(frozen=True, slots=True)
class ICAnalysisAttachmentRequest:
    analysis_type: str
    target_refs: tuple[str, ...]
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        analysis_type = str(self.analysis_type or "").strip()
        if not analysis_type:
            raise ValueError("analysis_type must be non-empty text")
        object.__setattr__(self, "analysis_type", analysis_type)
        object.__setattr__(
            self, "target_refs", required_texts(self.target_refs, "target_refs"),
        )
        if not isinstance(self.parameters, Mapping):
            raise ValueError("analysis parameters must be an object")
        object.__setattr__(self, "parameters", dict(self.parameters))

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_type": self.analysis_type,
            "target_refs": list(self.target_refs),
            "parameters": dict(self.parameters),
        }

    @classmethod
    def from_dict(cls, value: Any) -> ICAnalysisAttachmentRequest:
        if not isinstance(value, dict):
            raise ValueError("IC analysis attachment must be an object")
        return cls(
            value.get("analysis_type"),
            tuple(value.get("target_refs") or ()),
            value.get("parameters") or {},
        )


__all__ = ["ICAnalysisAttachmentRequest"]
