"""Resolve and synchronize one Profile-owned Graph report."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.research_reporting.authoring import (
    ensure_branch_report_chapter,
)
from tools.cli.release.research_reporting.authoring.tree_descriptor import (
    merge_section_refs,
)


@dataclass(frozen=True)
class LocalGraphReport:
    client_root: Path
    profile_id: str
    agent_id: str
    instance_id: str
    branch_id: str
    store: LocalProfileStore
    profile: dict[str, Any]
    record: dict[str, Any]

    @property
    def package_root(self) -> Path:
        return (
            Path(self.profile["workspace_root"]).expanduser()
            / "research" / self.record["record_id"]
        )


def profile_id_from_ref(profile_ref: str) -> str:
    prefix = "profile:"
    return profile_ref[len(prefix):] if profile_ref.startswith(prefix) else ""


def resolve_local_graph_report(
    *,
    client_root: Path,
    profile_id: str,
    agent_id: str,
    instance_id: str,
    branch_id: str,
) -> LocalGraphReport:
    store = LocalProfileStore(client_root)
    profile = store.load(profile_id)
    branch_ref = f"graph-branch:{instance_id}:{branch_id}"
    records = [
        item for item in profile["research_records"]
        if item["graph_branch_ref"] == branch_ref
        and (not agent_id or item["agent_id"] == agent_id)
    ]
    if len(records) != 1:
        raise ValueError(
            "local research record for the selected Graph branch "
            "must resolve exactly once"
        )
    record = records[0]
    package_root = (
        Path(profile["workspace_root"]).expanduser()
        / "research" / record["record_id"]
    )
    if not package_root.is_dir():
        raise ValueError("Work Package is not initialized locally")
    return LocalGraphReport(
        client_root=client_root,
        profile_id=profile_id,
        agent_id=str(record["agent_id"]),
        instance_id=instance_id,
        branch_id=branch_id,
        store=store,
        profile=profile,
        record=record,
    )


def synchronize_node_chapter(
    scope: LocalGraphReport,
    *,
    node_id: str,
    commit: bool = True,
) -> dict[str, Any]:
    report = ensure_branch_report_chapter(
        workspace_root=Path(scope.profile["workspace_root"]),
        work_package_id=scope.record["record_id"],
        title=scope.record["title"],
        node_id=node_id,
        branch_id=scope.branch_id,
        branch_ref=(
            f"graph-branch:{scope.instance_id}:{scope.branch_id}"
        ),
        commit=commit,
    )
    persist_report_descriptor(scope, report["descriptor"])
    return {
        "status": "synchronized",
        "node_id": node_id,
        **report["chapter_sync"],
        "report_file": str(report["paths"]["head"]),
    }


def persist_report_descriptor(
    scope: LocalGraphReport,
    descriptor: dict[str, Any],
) -> None:
    descriptor = dict(descriptor)
    previous = next((
        item for item in scope.record["artifacts"]
        if item.get("artifact_ref") == descriptor["artifact_ref"]
    ), {})
    descriptor["section_refs"] = merge_section_refs(
        previous.get("section_refs") or [],
        descriptor["section_refs"],
    )
    updated = dict(scope.record)
    updated["artifacts"] = [
        item for item in scope.record["artifacts"]
        if item["artifact_ref"] != descriptor["artifact_ref"]
    ] + [descriptor]
    scope.store.upsert_research_record(scope.profile_id, updated)
