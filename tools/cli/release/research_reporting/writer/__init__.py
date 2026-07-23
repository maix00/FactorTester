"""Derived local research report publication Interface."""

from . import index
from .index import ReportTarget
from .service import render_branch_report

__all__ = ["ReportTarget", "index", "render_branch_report"]
