"""Validation for optional, immutable local-report identity on a ResearchRun."""

from __future__ import annotations

import re
from typing import Any


_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
# A report is a logical catalog identity, not a package/branch path component.
# Keep legacy report IDs and the report:v1 IDs returned by research report-create.
_REPORT_IDENTIFIER = re.compile(r"^(?:report:v1:)?[A-Za-z0-9._-]{1,128}$")
_PROFILE_REF = re.compile(r"^profile:[A-Za-z0-9._-]{1,128}$")
_WORK_PACKAGE_REF = re.compile(r"^work-package:[A-Za-z0-9._-]{1,128}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = {
    "profile_ref",
    "work_package_ref",
    "instance_id",
    "branch_id",
    "report_id",
    "report_generation",
    "report_head_hash",
}
_DIRECT_FIELDS = {
    "binding_origin",
    "profile_ref",
    "work_package_ref",
    "branch_id",
    "report_id",
    "report_generation",
    "report_head_hash",
    "report_parent_id",
}


def normalize_report_binding(
    value: dict[str, Any] | None,
    *,
    trial_binding: dict[str, Any] | None,
    branch_snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    """Validate an opt-in report binding and add the server-owned node."""
    if value is None:
        return None
    if isinstance(value, dict) and value.get("binding_origin") is not None:
        return _normalize_direct_report_binding(value, trial_binding)
    if trial_binding is None:
        raise ValueError("report_binding requires trial_binding")
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError(
            "report_binding must contain the complete frozen report identity"
        )
    for field in ("instance_id", "branch_id"):
        if not _IDENTIFIER.fullmatch(str(value.get(field) or "")):
            raise ValueError(f"report_binding.{field} is invalid")
    if not _REPORT_IDENTIFIER.fullmatch(str(value.get("report_id") or "")):
        raise ValueError("report_binding.report_id is invalid")
    if not _PROFILE_REF.fullmatch(str(value.get("profile_ref") or "")):
        raise ValueError("report_binding.profile_ref is invalid")
    if not _WORK_PACKAGE_REF.fullmatch(
        str(value.get("work_package_ref") or "")
    ):
        raise ValueError("report_binding.work_package_ref is invalid")
    if not _HASH.fullmatch(str(value.get("report_head_hash") or "")):
        raise ValueError("report_binding.report_head_hash is invalid")
    generation = value.get("report_generation")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 0
    ):
        raise ValueError("report_binding.report_generation is invalid")
    expected = {
        "instance_id": str(trial_binding.get("instance_id") or ""),
        "branch_id": str(trial_binding.get("branch_id") or ""),
        "work_package_ref": str(
            branch_snapshot.get("work_package_ref") or ""
        ),
    }
    for field, expected_value in expected.items():
        if str(value.get(field) or "") != expected_value:
            raise ValueError(
                f"report_binding.{field} does not match the owned branch"
            )
    return {
        **value,
        "execution_node": str(branch_snapshot.get("execution_node") or ""),
    }


def _normalize_direct_report_binding(
    value: dict[str, Any],
    trial_binding: dict[str, Any] | None,
) -> dict[str, Any]:
    if set(value) != _DIRECT_FIELDS:
        raise ValueError(
            "direct report_binding must contain the complete frozen report identity"
        )
    origin = str(value.get("binding_origin") or "")
    if origin not in {"agent_direct", "report_direct"}:
        raise ValueError(
            "report_binding origin must be agent_direct or report_direct"
        )
    if origin == "agent_direct":
        if str((trial_binding or {}).get("binding_origin") or "") != "agent_direct":
            raise ValueError("agent_direct report_binding requires its TrialPlan")
    elif trial_binding is not None:
        raise ValueError(
            "report_direct report_binding must not carry a trial binding"
        )
    for field in ("branch_id", "report_parent_id"):
        if not _IDENTIFIER.fullmatch(str(value.get(field) or "")):
            raise ValueError(f"report_binding.{field} is invalid")
    if not _REPORT_IDENTIFIER.fullmatch(str(value.get("report_id") or "")):
        raise ValueError("report_binding.report_id is invalid")
    if not _PROFILE_REF.fullmatch(str(value.get("profile_ref") or "")):
        raise ValueError("report_binding.profile_ref is invalid")
    if not _WORK_PACKAGE_REF.fullmatch(
        str(value.get("work_package_ref") or "")
    ):
        raise ValueError("report_binding.work_package_ref is invalid")
    if not _HASH.fullmatch(str(value.get("report_head_hash") or "")):
        raise ValueError("report_binding.report_head_hash is invalid")
    generation = value.get("report_generation")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 0
    ):
        raise ValueError("report_binding.report_generation is invalid")
    return {**value, "execution_node": ""}
