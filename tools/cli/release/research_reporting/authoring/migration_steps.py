"""Bounded work-package migration steps for retired report sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..workspace_layout import ensure_work_package_layout
from .legacy_journal import journal_operations
from .legacy_projections import retire_verified_section_carriers, verify_legacy_projections
from .service import apply_branch_batch, ensure_branch_authoring, load_branch_authoring
from .tree_store import atomic_write


def ensure_tree(
    profile: dict[str, Any], record: dict[str, Any], package: Path,
    branch_id: str,
) -> None:
    ensure_work_package_layout(
        workspace_root=Path(profile["workspace_root"]), work_package_id=str(record["record_id"]),
        branch_id=branch_id, workspace_id=str(record["workspace_ref"]).removeprefix("workspace:"),
        title=str(record["title"]), branch_ref=str(record["graph_branch_ref"]),
        status=str(record["status"]), factor_family_versions=list(record["factor_family_versions"]),
    )
    ensure_branch_authoring(
        package_root=package, work_package_id=str(record["record_id"]), branch_id=branch_id,
        title=str(record["title"]), branch_ref=str(record["graph_branch_ref"]), commit=False,
    )


def import_journal(package: Path, work_package_id: str, path: Path) -> None:
    branch_id = path.parent.name
    snapshot = load_branch_authoring(package_root=package, branch_id=branch_id)
    operations = journal_operations(
        path, existing_ids={item["component_id"] for item in snapshot["components"]},
        existing_bindings={item["binding_id"] for item in snapshot["bindings"]},
        existing_assets={item["asset_ref"] for item in snapshot["head"]["assets"]},
    )
    for offset in range(0, len(operations), 128):
        apply_branch_batch(
            package_root=package, work_package_id=work_package_id, branch_id=branch_id,
            operations=operations[offset:offset + 128], materialize=False,
        )


def retire_legacy_projections(package: Path, journals: list[Path]) -> None:
    verify_legacy_projections(journals)
    for journal in journals:
        branch = journal.parent
        journal.unlink()
        branch.joinpath("LOGICAL_JOURNAL.json").unlink(missing_ok=True)
        retire_verified_section_carriers(branch)
    package.joinpath("INDEX.json").unlink(missing_ok=True)
    package.joinpath("REPORT.md").unlink(missing_ok=True)


def write_receipt(
    package: Path, *, name: str, record: dict[str, Any],
    sources: list[dict[str, str]], branches: list[str], journals: list[Path],
) -> Path:
    path = package / "migrations" / f"{name}.json"
    payload = {
        "schema_version": 1, "migration": name,
        "record_id": record["record_id"], "branches": branches,
        "sources": sources,
        "journals": [str(path) for path in journals],
    }
    atomic_write(path, json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True,
    ).encode() + b"\n")
    return path


def missing_head_branches(package: Path, branch_ids: list[str]) -> list[str]:
    return [
        branch for branch in branch_ids
        if not (package / "branches" / branch / "authoring" / "HEAD.json").is_file()
    ]
