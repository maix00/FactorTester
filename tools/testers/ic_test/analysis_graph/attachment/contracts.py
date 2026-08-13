"""Stable, client-readable reasons for analysis attachment decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AnalysisAttachmentIssue:
    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code or not self.message:
            raise ValueError("attachment issue requires code and message")
        object.__setattr__(self, "details", dict(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class AnalysisAttachmentAssessment:
    analysis_type: str
    target_refs: tuple[str, ...]
    issues: tuple[AnalysisAttachmentIssue, ...] = ()

    @property
    def compatible(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_type": self.analysis_type,
            "target_refs": list(self.target_refs),
            "compatible": self.compatible,
            "issues": [issue.to_dict() for issue in self.issues],
        }


__all__ = ["AnalysisAttachmentAssessment", "AnalysisAttachmentIssue"]
