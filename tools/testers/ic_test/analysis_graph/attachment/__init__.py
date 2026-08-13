"""Attachment compatibility projections for IC analysis authoring."""

from .contracts import AnalysisAttachmentAssessment, AnalysisAttachmentIssue
from .evaluator import assess_analysis_attachment, list_analysis_attachment_candidates

__all__ = [
    "AnalysisAttachmentAssessment",
    "AnalysisAttachmentIssue",
    "assess_analysis_attachment",
    "list_analysis_attachment_candidates",
]
