#!/usr/bin/env python3
"""Explicitly collapse legacy per-Branch Report IDs inside one Work Package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.cli.release.research_reporting.authoring.tree_paths import (
    report_tree_paths,
)
from tools.cli.release.research_reporting.authoring.tree_store import (
    atomic_write,
    load_head,
    write_head,
)
from tools.cli.release.research_reporting.package_layout import (
    safe_package_component,
)
from tools.cli.release.research_reporting.work_package_identity import (
    ensure_work_package_identity,
)

RECEIPT = "work-package-report-identity-migration.json"


def migrate(package_root: Path, *, apply: bool) -> dict[str, Any]:
    root = Path(package_root).expanduser().resolve()
    package_id = safe_package_component(root.name, field="work_package_id")
    branches: dict[str, str] = {}
    for head_path in sorted(root.glob("branches/*/authoring/HEAD.json")):
        branch_id = safe_package_component(
            head_path.parent.parent.name, field="branch_id",
        )
        branches[branch_id] = str(
            load_head(report_tree_paths(root, branch_id))["report_id"]
        )
    if not branches:
        raise ValueError("Work Package contains no Branch report HEAD")
    report_ids = sorted(set(branches.values()))
    canonical = report_ids[0] if len(report_ids) == 1 else f"report-{package_id}"
    result: dict[str, Any] = {
        "status": "planned" if not apply else "migrated",
        "work_package_id": package_id,
        "report_id": canonical,
        "branch_count": len(branches),
        "legacy_report_ids": report_ids,
        "changed_branch_count": sum(value != canonical for value in branches.values()),
    }
    if not apply:
        return result
    for branch_id, previous in branches.items():
        if previous == canonical:
            continue
        paths = report_tree_paths(root, branch_id)
        write_head(paths, {**load_head(paths), "report_id": canonical})
    ensure_work_package_identity(
        root, work_package_id=package_id, report_id=canonical,
    )
    receipt = {
        "schema_version": 1,
        "work_package_id": package_id,
        "report_id": canonical,
        "branches": branches,
    }
    atomic_write(
        root / RECEIPT,
        (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode(),
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package_root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate(args.package_root, apply=args.apply), ensure_ascii=False))


if __name__ == "__main__":
    main()
