"""Branch-scoped structured authoring sources for Work Package reports."""

from .service import (
    authoring_paths,
    ensure_branch_authoring,
    load_branch_authoring,
    save_branch_authoring,
)
from .profile_sync import ensure_branch_report_chapter

__all__ = [
    "authoring_paths",
    "ensure_branch_authoring",
    "load_branch_authoring",
    "save_branch_authoring",
    "ensure_branch_report_chapter",
]
