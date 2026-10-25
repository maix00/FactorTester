#!/usr/bin/env python3
"""Migrate legacy Job report directories into CouchDB ReportDocuments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.jobs.storage.couchdb_reports import (
    CouchDBObjectStore,
    publish_job_report,
)


def legacy_report_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    return sorted(
        path for path in root.iterdir()
        if path.is_dir() and any(item.is_file() for item in path.iterdir())
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--couchdb-url", required=True)
    parser.add_argument("--database", default="ft_objects")
    parser.add_argument("--owner", default="__legacy_report_migration__")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    directories = legacy_report_dirs(args.root)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "reports": len(directories)}))
        return 0
    store = CouchDBObjectStore(args.couchdb_url, args.database)
    migrated = []
    for directory in directories:
        ref = publish_job_report(
            job_id=directory.name, attempt=1, owner=args.owner,
            reports_dir=str(directory),
            metadata={"migrated_from": str(directory)}, store=store,
        )
        migrated.append({"directory": str(directory), "report_ref": ref})
    print(json.dumps({"migrated": migrated}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
