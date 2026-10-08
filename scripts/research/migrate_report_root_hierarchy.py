#!/usr/bin/env python3
"""Audit or repair root-level legacy content in current report trees."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.cli.release.research_reporting.authoring.export import export_branch_report
from tools.cli.release.research_reporting.report_workspace_identity import (
    load_report_workspace_identity,
)
from tools.cli.release.research_reporting.maintenance.root_hierarchy import (
    inspect_root_hierarchy,
    migrate_single_chapter_root,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--users-root", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    reports = sorted(args.users_root.glob(
        "*/profiles/*/research/*/branches/*/authoring/HEAD.json"
    ))
    results = []
    for head in reports:
        branch_root = head.parents[1]
        package_root = branch_root.parents[1]
        branch_id = branch_root.name
        plan = inspect_root_hierarchy(
            package_root=package_root, branch_id=branch_id,
        )
        result = {
            "report": str(branch_root.relative_to(args.users_root)),
            **plan,
        }
        if args.apply and plan["status"] == "migratable":
            migrated = migrate_single_chapter_root(
                package_root=package_root, branch_id=branch_id,
            )
            result.update(migrated)
            # REPORT.md is a derived view of the canonical ReportBranch tree.
            # Export commits the changed tree and avoids leaving a stale view.
            identity = load_report_workspace_identity(package_root)
            result["report_export"] = export_branch_report(
                package_root=package_root,
                report_workspace_id=identity["report_workspace_id"],
                branch_id=branch_id,
                message="Migrate report root hierarchy",
            )
        results.append(result)
    print(json.dumps(
        {"reports": results}, ensure_ascii=False, indent=2, default=str,
    ))
    return 1 if any(item["status"] == "ambiguous" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
