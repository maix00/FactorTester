"""Public pure-local research report projections."""

from .markdown import MarkdownReportTarget
from .publisher import (
    finalize_historical_research_backfill,
    publish_research_checkpoint,
    stage_historical_research_checkpoint,
)
from .schema import canonical_report_snapshot
from .writer import ReportTarget, render_branch_report

__all__ = [
    "MarkdownReportTarget",
    "ReportTarget",
    "canonical_report_snapshot",
    "finalize_historical_research_backfill",
    "publish_research_checkpoint",
    "render_branch_report",
    "stage_historical_research_checkpoint",
]
