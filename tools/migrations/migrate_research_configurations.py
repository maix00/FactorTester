"""One-time migration to canonical ResearchConfiguration records."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3

import settings as Settings

from server.services.research_configurations import (
    migrate_legacy_templates,
    migrate_legacy_workspaces_and_runs,
)


def backup_database(target: Path | None = None) -> Path:
    source_path = Path(Settings.CACHE_DB_PATH)
    if target is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = source_path.with_name(f"{source_path.name}.research-config-{stamp}.bak")
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source_path) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply migration; default is dry-run.")
    parser.add_argument("--backup", type=Path, help="Backup path used before --apply.")
    args = parser.parse_args()
    backup = backup_database(args.backup) if args.apply else None
    report = {
        "workspace_and_runs": migrate_legacy_workspaces_and_runs(apply=args.apply),
        "templates": migrate_legacy_templates(apply=args.apply),
    }
    report["success"] = not (
        report["workspace_and_runs"]["errors"] or report["templates"]["errors"]
    )
    report["backup"] = str(backup) if backup else None
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
