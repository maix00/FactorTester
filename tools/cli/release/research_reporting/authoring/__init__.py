"""Branch-scoped structured authoring sources for Work Package reports."""

from .paths import authoring_paths
from .service import (
    ensure_branch_authoring,
    load_branch_authoring,
    save_branch_authoring,
)
from .profile_sync import ensure_branch_report_chapter
from .migration import migrate_profile_work_packages

__all__ = [
    "authoring_paths",
    "ensure_branch_authoring",
    "load_branch_authoring",
    "save_branch_authoring",
    "ensure_branch_report_chapter",
    "migrate_profile_work_packages",
]
