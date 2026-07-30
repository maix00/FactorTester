"""Resolve one local Profile record to a report-tree branch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.research_branch_bindings import branch_bindings


@dataclass(frozen=True)
class BranchReportScope:
    client_root: Path
    profile_id: str
    profile: dict[str, Any]
    record: dict[str, Any]
    work_package_id: str
    branch_id: str
    package_root: Path
    graph_branch_ref: str

    @property
    def branch_ref(self) -> str:
        return self.graph_branch_ref


def resolve_branch_report_scope(
    *, client_root: Path, profile_id: str, work_package_id: str,
    branch_id: str,
) -> BranchReportScope:
    """Resolve a current branch or an already registered historical artifact."""
    profile = LocalProfileStore(client_root).load(profile_id)
    records = _package_records(profile, work_package_id)
    records = [
        item for item in records
        if any(
            _matches_branch(binding["branch_ref"], branch_id)
            for binding in branch_bindings(item)
        )
        or _owns_report_branch(item, branch_id)
    ]
    return _scope(
        client_root=client_root, profile_id=profile_id, profile=profile,
        records=records, work_package_id=work_package_id, branch_id=branch_id,
    )


def resolve_history_migration_scope(
    *, client_root: Path, profile_id: str, work_package_id: str,
    branch_id: str,
) -> BranchReportScope:
    """Resolve one locally materialized lineage branch for one-time migration."""
    profile = LocalProfileStore(client_root).load(profile_id)
    records = _package_records(profile, work_package_id)
    return _scope(
        client_root=client_root, profile_id=profile_id, profile=profile,
        records=records, work_package_id=work_package_id, branch_id=branch_id,
        require_authoring=True,
    )


def _scope(
    *, client_root: Path, profile_id: str, profile: dict[str, Any],
    records: list[dict[str, Any]], work_package_id: str, branch_id: str,
    require_authoring: bool = False,
) -> BranchReportScope:
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
    if require_authoring and not (
        package_root / "branches" / branch_id / "authoring" / "HEAD.json"
    ).is_file():
        raise ValueError("historical report branch is not materialized locally")
    resolved_ref = next((
        str(binding["branch_ref"])
        for binding in branch_bindings(records[0])
        if _matches_branch(str(binding["branch_ref"]), branch_id)
    ), f"report-branch:{branch_id}")
    return BranchReportScope(
        client_root=client_root, profile_id=profile_id, profile=profile,
        record=records[0], work_package_id=work_package_id,
        branch_id=branch_id, package_root=package_root,
        graph_branch_ref=resolved_ref,
    )


def _package_records(
    profile: dict[str, Any], work_package_id: str,
) -> list[dict[str, Any]]:
    return [
        item for item in profile["research_records"]
        if item["graph_instance_ref"] == f"work-package:{work_package_id}"
    ]


def _matches_branch(reference: str, branch_id: str) -> bool:
    if reference == f"report-branch:{branch_id}":
        return True
    parts = reference.split(":")
    return (
        len(parts) == 3 and parts[0] == "graph-branch"
        and bool(parts[1]) and parts[2] == branch_id
    )


def _owns_report_branch(record: dict[str, Any], branch_id: str) -> bool:
    marker = f"/branches/{branch_id}/"
    return any(
        marker in str(item.get("artifact_ref") or "")
        for item in record.get("artifacts") or []
        if isinstance(item, dict)
    )
