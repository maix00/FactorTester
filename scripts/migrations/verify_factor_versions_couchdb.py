#!/usr/bin/env python3
"""Verify frozen RunSpec factor refs exist as CouchDB FactorVersion docs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.jobs.storage.couchdb_objects import get_object
from server.jobs.storage.couchdb_reports import CouchDBObjectStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-spec", type=Path, required=True)
    parser.add_argument("--couchdb-url", required=True)
    parser.add_argument("--database", default="ft_objects")
    args = parser.parse_args(argv)
    spec = json.loads(args.run_spec.read_text())
    factors = ((spec.get("run_spec") or spec).get("configuration", {})
               .get("shared", {}).get("factors") or [])
    store = CouchDBObjectStore(args.couchdb_url, args.database)
    refs = [str(item.get("ref") or "") for item in factors
            if str(item.get("ref") or "").startswith("factor:v2:")]
    missing = []
    for ref in refs:
        try:
            document = get_object(store, ref)
            if document.get("kind") != "factor_version":
                missing.append(ref)
        except Exception:
            missing.append(ref)
    print(json.dumps({"checked": len(refs), "missing": missing}, indent=2))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
