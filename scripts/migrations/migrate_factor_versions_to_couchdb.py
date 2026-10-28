#!/usr/bin/env python3
"""Migrate frozen RunSpec factor records into CouchDB FactorVersion docs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.jobs.storage.couchdb_objects import VersionedObject, put_object
from server.jobs.storage.couchdb_reports import CouchDBObjectStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-spec", type=Path, required=True)
    parser.add_argument("--couchdb-url", required=True)
    parser.add_argument("--database", default="ft_objects")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    spec = json.loads(args.run_spec.read_text())
    factors = (
        (spec.get("run_spec") or spec).get("configuration", {})
        .get("shared", {}).get("factors") or []
    )
    store = None if args.dry_run else CouchDBObjectStore(
        args.couchdb_url, args.database,
    )
    migrated = []
    for factor in factors:
        ref = str(factor.get("ref") or "")
        if not ref.startswith("factor:v2:"):
            continue
        if store is not None:
            put_object(store, VersionedObject(
                ref=ref, kind="factor_version",
                owner=str(factor.get("owner_ref") or ""), payload=factor,
            ))
        migrated.append(ref)
    print(json.dumps({"dry_run": args.dry_run, "count": len(migrated),
                      "refs": migrated}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
