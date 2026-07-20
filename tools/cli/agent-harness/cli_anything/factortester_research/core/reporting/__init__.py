"""Deterministic cold-path projections for local research reports."""

from .markdown import MarkdownReportTarget
from .schema import canonical_report_snapshot
from .writer import ReportTarget, render_branch_report

__all__ = [
    "MarkdownReportTarget",
    "ReportTarget",
    "canonical_report_snapshot",
    "render_branch_report",
]
