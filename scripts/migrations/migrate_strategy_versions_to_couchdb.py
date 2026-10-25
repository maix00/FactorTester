#!/usr/bin/env python3
"""Migrate strategy library entries/revisions into CouchDB StrategyVersion docs."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from server.jobs.storage.couchdb_objects import VersionedObject, put_object
from server.jobs.storage.couchdb_reports import CouchDBObjectStore


def strategy_documents(db_path: Path) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        entries = conn.execute(
            "SELECT * FROM strategy_library_entries WHERE deleted_at=0"
        ).fetchall()
        result = []
        for entry in entries:
            revision = conn.execute(
                "SELECT * FROM strategy_library_revisions WHERE revision_ref=?",
                (entry["current_revision_ref"],),
            ).fetchone()
            result.append({
                "ref": entry["strategy_ref"],
                "owner": entry["owner_ref"],
                "payload": {
                    "entry": {key: entry[key] for key in entry.keys()},
                    "revision": (
                        {key: revision[key] for key in revision.keys()}
                        if revision is not None else None
                    ),
                },
            })
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--couchdb-url", required=True)
    parser.add_argument("--database", default="ft_objects")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    documents = strategy_documents(args.db)
    if not args.dry_run:
        store = CouchDBObjectStore(args.couchdb_url, args.database)
        for item in documents:
            put_object(store, VersionedObject(
                ref=item["ref"], kind="strategy_version",
                owner=item["owner"], payload=item["payload"],
            ))
    print(json.dumps({"dry_run": args.dry_run, "count": len(documents),
                      "refs": [item["ref"] for item in documents]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
