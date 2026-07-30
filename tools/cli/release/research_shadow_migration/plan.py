"""Deterministic local Profile/report migration manifest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..local_profile import LocalProfileStore
from .common import (
    branch_id,
    canonical_hash,
    file_hash,
    git_head,
    validate_shadow_record,
)


def plan_local_shadow_migration(
    *,
    client_root: Path,
    profile_id: str,
    source_work_package_id: str,
    retained_instance_id: str,
    retained_branch_id: str,
    retired_instance_ids: list[str],
    server_plan_hash: str,
) -> dict[str, Any]:
    profile = LocalProfileStore(client_root).load(profile_id)
    records = {
        str(item["record_id"]): item
        for item in profile["research_records"]
    }
    source = records.get(source_work_package_id)
    retained = records.get(retained_instance_id)
    retired = [records.get(item) for item in retired_instance_ids]
    if source is None or retained is None or any(item is None for item in retired):
        raise ValueError("local shadow migration records are incomplete")
    validate_shadow_record(
        retained,
        source_work_package_id=source_work_package_id,
        instance_id=retained_instance_id,
        branch_id=retained_branch_id,
    )
    for instance_id, record in zip(retired_instance_ids, retired, strict=True):
        assert record is not None
        validate_shadow_record(
            record,
            source_work_package_id=source_work_package_id,
            instance_id=instance_id,
            branch_id=branch_id(str(record["graph_branch_ref"])),
        )
    workspace_root = Path(profile["workspace_root"]).expanduser().resolve()
    research_root = workspace_root / "research"
    source_root = research_root / source_work_package_id
    retained_root = research_root / retained_instance_id
    target_head = (
        source_root / "branches" / retained_branch_id
        / "authoring" / "HEAD.json"
    )
    if target_head.exists():
        raise ValueError("retained branch is already materialized in source")
    roots = [source_root, retained_root, *[
        research_root / item for item in retired_instance_ids
    ]]
    if not all(path.is_dir() and path.parent == research_root for path in roots):
        raise ValueError("local shadow migration roots are invalid")
    projection = {
        "schema_version": 1,
        "profile_id": profile_id,
        "source_work_package_id": source_work_package_id,
        "retained_instance_id": retained_instance_id,
        "retained_branch_id": retained_branch_id,
        "retained_branch_ref": str(retained["graph_branch_ref"]),
        "source_branch_ref": str(
            (retained.get("provenance") or {}).get(
                "source_graph_branch_ref"
            ) or ""
        ),
        "retired_instance_ids": retired_instance_ids,
        "server_plan_hash": server_plan_hash,
        "source_git_head": git_head(source_root),
        "retained_git_head": git_head(retained_root),
        "retained_report_head_hash": file_hash(
            retained_root / "branches" / retained_branch_id
            / "authoring" / "HEAD.json"
        ),
    }
    return {**projection, "plan_hash": canonical_hash(projection)}
