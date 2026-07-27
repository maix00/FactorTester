"""One-shot normalization of local research identity references.

The local profile contract uses the stable Work Package identity for the
record and a physical instance identity for each branch.  Older descriptors
used ``graph-instance:`` or omitted the instance component from a branch
reference.  Those descriptors are rewritten before they are returned to any
consumer; readers do not carry a legacy compatibility path.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def migrate_research_identity(
    profile: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, int]]:
    """Normalize every local research record and return a small receipt."""
    migrated = deepcopy(profile)
    records = []
    changed = 0
    for record in profile.get("research_records") or []:
        candidate = deepcopy(record)
        if _normalize_record(candidate):
            changed += 1
        records.append(candidate)
    migrated["research_records"] = records
    return migrated, {
        "records_seen": len(records),
        "records_migrated": changed,
    }


def _normalize_record(record: dict[str, Any]) -> bool:
    record_id = str(record.get("record_id") or "").strip()
    if not record_id:
        return False

    old_instance_ref = str(record.get("graph_instance_ref") or "").strip()
    instance_id = _reference_id(old_instance_ref, "work-package:")
    if not instance_id:
        instance_id = _reference_id(old_instance_ref, "graph-instance:")
    if not instance_id:
        instance_id = record_id

    canonical_instance_ref = f"work-package:{record_id}"
    old_branch_ref = str(record.get("graph_branch_ref") or "").strip()
    canonical_branch_ref = _normalize_branch_ref(
        old_branch_ref,
        instance_id=instance_id,
    )
    changed = (
        old_instance_ref != canonical_instance_ref
        or old_branch_ref != canonical_branch_ref
    )
    record["graph_instance_ref"] = canonical_instance_ref
    record["graph_branch_ref"] = canonical_branch_ref
    return changed


def _reference_id(value: str, prefix: str) -> str:
    if not value.startswith(prefix):
        return ""
    return value[len(prefix):].strip()


def _normalize_branch_ref(value: str, *, instance_id: str) -> str:
    if not value:
        return ""
    if not value.startswith("graph-branch:"):
        return value
    parts = value.removeprefix("graph-branch:").split(":")
    if len(parts) == 2 and all(part.strip() for part in parts):
        return value
    if len(parts) == 1 and parts[0].strip() and instance_id:
        return f"graph-branch:{instance_id}:{parts[0].strip()}"
    return value
