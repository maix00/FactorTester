"""Compatibility exports for the public local reporting implementation."""

from tools.cli.release.research_reporting import (
    MarkdownReportTarget,
    ReportTarget,
    canonical_report_snapshot,
    render_branch_report,
)

__all__ = [
    "MarkdownReportTarget",
    "ReportTarget",
    "canonical_report_snapshot",
    "render_branch_report",
]
