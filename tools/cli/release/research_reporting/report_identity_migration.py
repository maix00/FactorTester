"""Explicitly unify legacy per-Branch Report IDs within one Report Workspace."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .authoring.tree_paths import report_tree_paths
from .authoring.tree_store import (
    HEAD_SCHEMA_VERSION,
    atomic_write,
    load_head,
    load_json,
    validate_head,
    write_head,
)
from .package_layout import safe_package_component
from .report_workspace_identity import ensure_report_workspace_identity

MIGRATION_RECEIPT = "report-workspace-report-identity-migration.json"


def migrate_report_workspace_identity(
    report_root: Path, *, apply: bool,
) -> dict[str, Any]:
    """Plan or apply the explicit legacy per-Branch report identity migration.

    This operates only on report HEAD metadata. It does not read or recreate
    graph workflow, checkpoint, or timeline state.
    """
    root = Path(report_root).expanduser().resolve()
    workspace_id = safe_package_component(
        root.name, field="report_workspace_id",
    )
    branches: dict[str, dict[str, Any]] = {}
    for head_path in sorted(root.glob("branches/*/authoring/HEAD.json")):
        branch_id = safe_package_component(
            head_path.parent.parent.name, field="branch_id",
        )
        branches[branch_id] = _load_migration_head(root, branch_id)
    if not branches:
        raise ValueError("Report Workspace contains no Branch report HEAD")

    report_ids = sorted({str(head["report_id"]) for head in branches.values()})
    canonical = (
        report_ids[0] if len(report_ids) == 1
        else f"report-{workspace_id}"
    )
    result: dict[str, Any] = {
        "status": "migrated" if apply else "planned",
        "report_workspace_id": workspace_id,
        "report_id": canonical,
        "branch_count": len(branches),
        "legacy_report_ids": report_ids,
        "changed_branch_count": sum(
            head["report_id"] != canonical for head in branches.values()
        ),
        "upgraded_head_count": sum(
            head["schema_version"] != HEAD_SCHEMA_VERSION
            for head in branches.values()
        ),
    }
    if not apply:
        return result

    previous_ids = {
        branch_id: str(head["report_id"])
        for branch_id, head in branches.items()
    }
    for branch_id, head in branches.items():
        if (
            head["report_id"] == canonical
            and head["schema_version"] == HEAD_SCHEMA_VERSION
        ):
            continue
        write_head(report_tree_paths(root, branch_id), {
            **head,
            "schema_version": HEAD_SCHEMA_VERSION,
            "report_id": canonical,
        })

    ensure_report_workspace_identity(
        root,
        report_workspace_id=workspace_id,
        report_id=canonical,
    )
    receipt = {
        "schema_version": 1,
        "report_workspace_id": workspace_id,
        "report_id": canonical,
        "branches": previous_ids,
    }
    atomic_write(
        root / MIGRATION_RECEIPT,
        (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode(),
    )
    return result


def _load_migration_head(report_root: Path, branch_id: str) -> dict[str, Any]:
    paths = report_tree_paths(report_root, branch_id)
    value = load_json(paths["head"], label="报告 HEAD")
    if value.get("schema_version") == HEAD_SCHEMA_VERSION:
        return load_head(paths)
    if value.get("schema_version") != 2:
        raise ValueError("legacy report tree HEAD schema is unsupported")
    normalized = {**value, "schema_version": HEAD_SCHEMA_VERSION}
    validate_head(normalized)
    return value
