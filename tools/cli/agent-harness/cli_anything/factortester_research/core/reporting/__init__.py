"""Pure render primitives; report writes use the scoped ``report`` CLI."""

from tools.cli.release.research_reporting import (
    MarkdownReportTarget,
    canonical_report_snapshot,
)

__all__ = [
    "MarkdownReportTarget",
    "canonical_report_snapshot",
]
