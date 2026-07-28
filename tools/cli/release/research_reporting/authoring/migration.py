"""One-shot migration from the abandoned root report path to Work Packages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...local_profile import LocalProfileStore
from .migration_record import migrate_record


def migrate_profile_work_packages(
    *, client_root: Path, profile_id: str, apply: bool,
) -> dict[str, Any]:
    """Migrate every local record owned by one Profile exactly once.

    Retired root/branch documents and physical journals are accepted only
    after schema and content-equivalence checks.  The historical projection
    files are removed only after the branch-owned report tree is rendered.
    Unrelated package material remains untouched.
    """
    store = LocalProfileStore(client_root)
    profile = store.load(profile_id)
    records = list(profile["research_records"])
    receipts = [
        migrate_record(profile, record, apply=apply)
        for record in records
    ]
    if apply:
        for receipt in receipts:
            replacement = receipt.get("record")
            if isinstance(replacement, dict):
                store.upsert_research_record(profile_id, replacement)
    return {
        "profile_id": profile_id,
        "apply": apply,
        "migrated_count": sum(
            item["status"] == "migrated" for item in receipts
        ),
        "ready_count": sum(item["status"] == "ready" for item in receipts),
        "skipped_count": sum(item["status"] == "skipped" for item in receipts),
        "items": [_public_receipt(item) for item in receipts],
    }


def _public_receipt(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item for key, item in value.items()
        if key not in {"record", "layout"}
    }
