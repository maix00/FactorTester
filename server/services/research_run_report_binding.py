"""Validate an optional frozen ReportBranch location for a ResearchRun."""

from __future__ import annotations

import re
from typing import Any


_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_REPORT_ID = re.compile(
    r"^(?:report:v1:[A-Za-z0-9_-]{1,160}|[A-Za-z0-9._-]{1,160})$"
)
_PROFILE_REF = re.compile(r"^profile:[A-Za-z0-9._:-]{1,160}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = {
    "profile_ref",
    "report_workspace_id",
    "branch_id",
    "report_id",
    "report_generation",
    "report_head_hash",
    "report_parent_id",
}


def normalize_report_binding(
    value: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Validate a report tree mount independently from Run sample-use state."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError(
            "report_binding must contain the complete frozen ReportBranch location"
        )
    for field in ("report_workspace_id", "branch_id", "report_parent_id"):
        if not _IDENTIFIER.fullmatch(str(value.get(field) or "")):
            raise ValueError(f"report_binding.{field} is invalid")
    if not _REPORT_ID.fullmatch(str(value.get("report_id") or "")):
        raise ValueError("report_binding.report_id is invalid")
    if not _PROFILE_REF.fullmatch(str(value.get("profile_ref") or "")):
        raise ValueError("report_binding.profile_ref is invalid")
    if not _HASH.fullmatch(str(value.get("report_head_hash") or "")):
        raise ValueError("report_binding.report_head_hash is invalid")
    generation = value.get("report_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise ValueError("report_binding.report_generation is invalid")

    return dict(value)
