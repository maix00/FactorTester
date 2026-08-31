"""One logical Report identity for every Research Work Package."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .authoring.tree_paths import report_tree_paths
from .authoring.tree_store import atomic_write, load_head
from .package_layout import safe_package_component

SCHEMA_VERSION = 1
MANIFEST = "work-package.json"


def ensure_work_package_identity(
    package_root: Path,
    *,
    work_package_id: str,
    report_id: str = "",
) -> dict[str, Any]:
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


def _existing_report_ids(root: Path) -> set[str]:
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
    safe_package_component(value.get("report_id"), field="report_id")
    return dict(value)


__all__ = ["ensure_work_package_identity", "work_package_report_id"]
