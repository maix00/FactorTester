"""Resolve a branch-owned report source from local Profile state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.research_reporting.authoring import (
    ensure_branch_authoring,
    load_branch_authoring,
)
from tools.cli.release.research_reporting.authoring.tree_descriptor import (
    merge_section_refs,
)


@dataclass(frozen=True)
class BranchReportScope:
    client_root: Path
    profile_id: str
    profile: dict[str, Any]
    record: dict[str, Any]
    work_package_id: str
    branch_id: str
    package_root: Path

    @property
    def branch_ref(self) -> str:
        return str(self.record["graph_branch_ref"])


def resolve_branch_report_scope(
    *, client_root: Path, profile_id: str, work_package_id: str,
    branch_id: str,
) -> BranchReportScope:
    """Resolve exactly one local record; never infer a root-level report."""
    store = LocalProfileStore(client_root)
    profile = store.load(profile_id)
    branch_ref = f"graph-branch:"
    records = [
        item for item in profile["research_records"]
        if item["graph_instance_ref"] == f"work-package:{work_package_id}"
        and item["graph_branch_ref"].startswith(branch_ref)
        and item["graph_branch_ref"].endswith(f":{branch_id}")
    ]
    if len(records) != 1:
        raise ValueError(
            "report requires exactly one local record for the Work Package branch"
        )
    package_root = (
        Path(profile["workspace_root"]).expanduser()
        / "research" / work_package_id
    )
    if not package_root.is_dir():
        raise ValueError("Work Package is not initialized locally")
    return BranchReportScope(
        client_root=client_root,
        profile_id=profile_id,
        profile=profile,
        record=records[0],
        work_package_id=work_package_id,
        branch_id=branch_id,
        package_root=package_root,
    )


def ensure_authoring(
    scope: BranchReportScope, *, node_id: str = "", materialize: bool = True,
) -> dict[str, Any]:
    """Create the exact branch source, then persist its descriptor locally."""
    result = ensure_branch_authoring(
        package_root=scope.package_root,
        work_package_id=scope.work_package_id,
        branch_id=scope.branch_id,
        title=scope.record["title"],
        branch_ref=scope.branch_ref,
        node_id=node_id,
        commit=False,
        materialize=materialize,
    )
    _replace_descriptor(scope, result["descriptor"])
    return result


def load_authoring(scope: BranchReportScope) -> dict[str, Any]:
    """Load the branch source after the caller has explicitly initialized it."""
    return load_branch_authoring(
        package_root=scope.package_root, branch_id=scope.branch_id,
    )


def persist_descriptor(scope: BranchReportScope, descriptor: dict[str, Any]) -> None:
    _replace_descriptor(scope, descriptor)


def _replace_descriptor(scope: BranchReportScope, descriptor: dict[str, Any]) -> None:
    record = dict(scope.record)
    existing = next((
        item for item in record["artifacts"]
        if item.get("artifact_ref") == descriptor["artifact_ref"]
    ), None)
    if isinstance(existing, dict):
        descriptor = {
            **descriptor,
            "section_refs": merge_section_refs(
                existing.get("section_refs") or [], descriptor["section_refs"],
            ),
        }
    record["artifacts"] = [
        item for item in record["artifacts"]
        if item["artifact_ref"] != descriptor["artifact_ref"]
    ] + [descriptor]
    LocalProfileStore(scope.client_root).upsert_research_record(
        scope.profile_id, record,
    )
