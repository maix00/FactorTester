"""Stable, client-readable reasons for analysis attachment decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..model import ICAnalysisNode


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


@dataclass(frozen=True, slots=True)
class AnalysisAttachmentPlan:
    analysis_type: str
    mapping: str
    target_refs: tuple[str, ...]
    parameters: Mapping[str, Any]
    nodes: tuple[ICAnalysisNode, ...] = ()
    existing_node_ids: tuple[str, ...] = ()
    issues: tuple[AnalysisAttachmentIssue, ...] = ()
    duplicate_target_count: int = 0

    @property
    def compatible(self) -> bool:
        return not self.issues

    @property
    def new_node_count(self) -> int:
        return len(self.nodes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_type": self.analysis_type,
            "mapping": self.mapping,
            "target_refs": list(self.target_refs),
            "parameters": dict(self.parameters),
            "compatible": self.compatible,
            "new_node_count": self.new_node_count,
            "nodes": [node.to_dict() for node in self.nodes],
            "existing_node_ids": list(self.existing_node_ids),
            "duplicate_target_count": self.duplicate_target_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


__all__ = [
    "AnalysisAttachmentAssessment",
    "AnalysisAttachmentIssue",
    "AnalysisAttachmentPlan",
]
