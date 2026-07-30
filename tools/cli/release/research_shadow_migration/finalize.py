"""Finalize local Profile ownership after the server transaction succeeds."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from ..local_profile import LocalProfileStore
from ..research_branch_bindings import with_branch_binding
from ..research_reporting.authoring.tree_descriptor import (
    report_tree_descriptor,
)
from ..research_reporting.authoring.tree_paths import report_tree_paths
from ..research_reporting.authoring.tree_store import load_head
from ..research_reporting.git import commit_work_package
from ..storage import write_json
from .common import validate_plan_hash


def finalize_local_shadow_migration(
    *,
    client_root: Path,
    plan: dict[str, Any],
    server_receipt: dict[str, Any],
) -> dict[str, Any]:
    validate_plan_hash(plan)
    if (
        server_receipt.get("status") != "applied"
        or server_receipt.get("plan_hash") != plan["server_plan_hash"]
    ):
        raise ValueError("server migration receipt does not match local plan")
    store = LocalProfileStore(client_root)
    profile = store.load(str(plan["profile_id"]))
    records = list(profile["research_records"])
    source = next((
        item for item in records
        if item["record_id"] == plan["source_work_package_id"]
    ), None)
    if source is None:
        raise ValueError("source local research record was not found")
    updated = with_branch_binding(
        source,
        branch_ref=str(plan["retained_branch_ref"]),
        kind="shadow_continuation",
        source_branch_ref=str(plan["source_branch_ref"]),
    )
    source_root = (
        Path(profile["workspace_root"]).expanduser().resolve()
        / "research" / str(plan["source_work_package_id"])
    )
    paths = report_tree_paths(source_root, str(plan["retained_branch_id"]))
    descriptor = report_tree_descriptor(
        package_root=source_root,
        work_package_id=str(plan["source_work_package_id"]),
        branch_id=str(plan["retained_branch_id"]),
        head=load_head(paths),
    )
    updated["artifacts"] = [
        item for item in updated["artifacts"]
        if item.get("artifact_ref") != descriptor["artifact_ref"]
    ] + [descriptor]
    obsolete = {
        str(plan["retained_instance_id"]),
        *[str(item) for item in plan["retired_instance_ids"]],
    }
    profile["research_records"] = [
        updated if item["record_id"] == updated["record_id"] else item
        for item in records if item["record_id"] not in obsolete
    ]
    store.save(profile)
    receipt = {
        "schema_version": 1,
        "status": "applied",
        "plan_hash": plan["plan_hash"],
        "server_plan_hash": plan["server_plan_hash"],
        "source_work_package_id": plan["source_work_package_id"],
        "retained_branch_ref": plan["retained_branch_ref"],
        "removed_local_record_ids": sorted(obsolete),
        "source_commit_before": plan["source_git_head"],
        "retained_commit_before": plan["retained_git_head"],
    }
    write_json(
        source_root / "migrations"
        / "shadow-work-package-ownership-v1.receipt.json",
        receipt,
    )
    final_git = commit_work_package(
        source_root, message="Record shadow Work Package migration",
    )
    deleted = []
    research_root = source_root.parent
    for item in sorted(obsolete):
        target = research_root / item
        if target.is_dir() and target.parent == research_root:
            shutil.rmtree(target)
            deleted.append(item)
    return {
        **receipt,
        "source_commit_after": final_git["commit"],
        "deleted_local_work_packages": deleted,
    }
