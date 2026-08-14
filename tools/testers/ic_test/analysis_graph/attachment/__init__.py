"""Attachment compatibility projections for IC analysis authoring."""

from .contracts import (
    AnalysisAttachmentAssessment,
    AnalysisAttachmentIssue,
    AnalysisAttachmentPlan,
)
from .evaluator import (
    assess_analysis_attachment,
    assess_analysis_selection,
    list_analysis_attachment_candidates,
)
from .planner import apply_analysis_attachment, plan_analysis_attachment

__all__ = [
    "AnalysisAttachmentAssessment",
    "AnalysisAttachmentIssue",
    "AnalysisAttachmentPlan",
    "apply_analysis_attachment",
    "assess_analysis_attachment",
    "assess_analysis_selection",
    "list_analysis_attachment_candidates",
    "plan_analysis_attachment",
]
