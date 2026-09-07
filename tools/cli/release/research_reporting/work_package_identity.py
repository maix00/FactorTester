"""One logical Report identity for every Research Work Package."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .package_layout import safe_package_component

SCHEMA_VERSION = 1
MANIFEST = "work-package.json"
MIGRATION_RECEIPT = "work-package-report-identity-migration.json"


def ensure_work_package_identity(
    package_root: Path,
    *,
    work_package_id: str,
    report_id: str = "",
) -> dict[str, Any]:
    from .authoring.tree_store import atomic_write

    root = Path(package_root).expanduser().resolve()
    package = safe_package_component(work_package_id, field="work_package_id")
    path = root / MANIFEST
    if path.is_file():
        value = _validate(json.loads(path.read_text(encoding="utf-8")))
        if value["work_package_id"] != package:
            raise ValueError("Work Package manifest identity conflicts with its directory")
        if report_id and value["report_id"] != report_id:
            raise ValueError(
                "a Work Package can target only one report_id; derive a new Report "
                "into a new Work Package"
            )
        return value

    existing = _existing_report_ids(root)
    if len(existing) > 1:
        raise ValueError(
            "legacy Work Package contains branch-specific report_id values; run "
            "the explicit Work Package Report identity migration before continuing"
        )
    selected = report_id or next(iter(existing), f"report-{package}")
    if existing and selected not in existing:
        raise ValueError("Work Package report_id conflicts with its existing Branch HEAD")
    value = _validate({
        "schema_version": SCHEMA_VERSION,
        "work_package_id": package,
        "report_id": selected,
    })
    atomic_write(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return value


def work_package_report_id(package_root: Path, work_package_id: str) -> str:
    return str(ensure_work_package_identity(
        package_root, work_package_id=work_package_id,
    )["report_id"])


def migrate_work_package_report_identity(
    package_root: Path, *, apply: bool,
) -> dict[str, Any]:
    """Plan or apply the explicit legacy per-Branch identity migration."""
    from .authoring.tree_paths import report_tree_paths
    from .authoring.tree_store import HEAD_SCHEMA_VERSION, atomic_write, write_head

    root = Path(package_root).expanduser().resolve()
    package_id = safe_package_component(root.name, field="work_package_id")
    branches: dict[str, dict[str, Any]] = {}
    for head_path in sorted(root.glob("branches/*/authoring/HEAD.json")):
        branch_id = safe_package_component(
            head_path.parent.parent.name, field="branch_id",
        )
        branches[branch_id] = load_work_package_migration_head(root, branch_id)
    if not branches:
        raise ValueError("Work Package contains no Branch report HEAD")
    report_ids = sorted({str(head["report_id"]) for head in branches.values()})
    canonical = report_ids[0] if len(report_ids) == 1 else f"report-{package_id}"
    result: dict[str, Any] = {
        "status": "migrated" if apply else "planned",
        "work_package_id": package_id,
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
        paths = report_tree_paths(root, branch_id)
        write_head(paths, {
            **head,
            "schema_version": HEAD_SCHEMA_VERSION,
            "report_id": canonical,
        })
    ensure_work_package_identity(
        root, work_package_id=package_id, report_id=canonical,
    )
    receipt = {
        "schema_version": 1,
        "work_package_id": package_id,
        "report_id": canonical,
        "branches": previous_ids,
    }
    atomic_write(
        root / MIGRATION_RECEIPT,
        (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode(),
    )
    return result


def load_work_package_migration_head(
    package_root: Path, branch_id: str,
) -> dict[str, Any]:
    """Read a current HEAD or the exact legacy v2 shape for migration only."""
    from .authoring.tree_paths import report_tree_paths
    from .authoring.tree_store import (
        HEAD_SCHEMA_VERSION,
        load_head,
        load_json,
        validate_head,
    )

    paths = report_tree_paths(package_root, branch_id)
    value = load_json(paths["head"], label="报告 HEAD")
    if value.get("schema_version") == HEAD_SCHEMA_VERSION:
        return load_head(paths)
    if value.get("schema_version") != 2:
        raise ValueError("legacy report tree HEAD schema is unsupported")
    normalized = {**value, "schema_version": HEAD_SCHEMA_VERSION}
    validate_head(normalized)
    return value


def _existing_report_ids(root: Path) -> set[str]:
    from .authoring.tree_paths import report_tree_paths
    from .authoring.tree_store import load_head

    values: set[str] = set()
    for head_path in sorted(root.glob("branches/*/authoring/HEAD.json")):
        branch_id = head_path.parent.parent.name
        values.add(str(load_head(report_tree_paths(root, branch_id))["report_id"]))
    return values


def _validate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "work_package_id", "report_id",
    }:
        raise ValueError("Work Package identity manifest is invalid")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Work Package identity schema is unsupported")
    safe_package_component(value.get("work_package_id"), field="work_package_id")
    # report_id is a logical catalog identity, never a filesystem component.
    # Catalog reports use report:v1:<id>; package and branch paths remain strict.
    report_id = value.get("report_id")
    if isinstance(report_id, str) and report_id.startswith("report:v1:"):
        safe_package_component(report_id.removeprefix("report:v1:"), field="report_id")
    else:
        safe_package_component(report_id, field="report_id")
    return dict(value)


__all__ = [
    "ensure_work_package_identity",
    "load_work_package_migration_head",
    "migrate_work_package_report_identity",
    "work_package_report_id",
]
