"""Stage the retained report branch inside its logical Work Package."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..local_profile import LocalProfileStore
from ..research_reporting.authoring.export import export_branch_report
from ..research_reporting.authoring.tree_fork import (
    inherit_report_tree_across_packages,
)
from ..research_reporting.authoring.tree_paths import report_tree_paths
from ..research_reporting.git import commit_work_package
from .common import file_hash, git_head, validate_plan_hash


def stage_local_shadow_migration(
    *,
    client_root: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    validate_plan_hash(plan)
    profile = LocalProfileStore(client_root).load(str(plan["profile_id"]))
    research_root = (
        Path(profile["workspace_root"]).expanduser().resolve() / "research"
    )
    source_root = research_root / str(plan["source_work_package_id"])
    retained_root = research_root / str(plan["retained_instance_id"])
    if git_head(source_root) != plan["source_git_head"]:
        raise ValueError("source Work Package changed after migration plan")
    if git_head(retained_root) != plan["retained_git_head"]:
        raise ValueError("retained shadow changed after migration plan")
    retained_branch_id = str(plan["retained_branch_id"])
    source_paths = report_tree_paths(retained_root, retained_branch_id)
    if file_hash(source_paths["head"]) != plan["retained_report_head_hash"]:
        raise ValueError("retained report HEAD changed after migration plan")
    inherited = inherit_report_tree_across_packages(
        source_package_root=retained_root,
        target_package_root=source_root,
        source_branch_id=retained_branch_id,
        target_branch_id=retained_branch_id,
        target_report_id=(
            f"report-{plan['source_work_package_id']}-{retained_branch_id}"
        ),
    )
    export_branch_report(
        package_root=source_root,
        work_package_id=str(plan["source_work_package_id"]),
        branch_id=retained_branch_id,
        commit=False,
    )
    git = commit_work_package(
        source_root,
        message="Migrate shadow branch into logical Work Package",
    )
    return {
        "status": "staged",
        "inherited": inherited["inherited"],
        "source_commit": git["commit"],
    }
