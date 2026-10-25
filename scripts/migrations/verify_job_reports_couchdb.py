#!/usr/bin/env python3
"""Verify legacy report directories against CouchDB ReportDocuments."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from server.jobs.storage.couchdb_reports import CouchDBObjectStore, content_name


def verify_dir(store: CouchDBObjectStore, directory: Path) -> dict[str, object]:
    ref = f"report:{directory.name}:1"
    try:
        _, raw = store._request("GET", ref)
        doc = json.loads(raw)
    except Exception as exc:
        return {"directory": str(directory), "ok": False, "error": type(exc).__name__}
    attachments = doc.get("attachments") or {}
    checked = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name == "nautilus_receipt.json":
            continue
        stored = attachments.get(path.name)
        if not stored:
            return {"directory": str(directory), "ok": False, "error": f"missing {path.name}"}
        data = store.get_attachment(ref, stored)
        digest = hashlib.sha256(data).hexdigest()
        if stored != content_name(path.read_bytes(), path.suffix.lstrip(".")):
            return {"directory": str(directory), "ok": False, "error": f"name {path.name}"}
        if digest != stored.split(".", 1)[0]:
            return {"directory": str(directory), "ok": False, "error": f"hash {path.name}"}
        checked.append(path.name)
    return {"directory": str(directory), "ok": True, "files": checked}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--couchdb-url", required=True)
    parser.add_argument("--database", default="ft_objects")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    store = CouchDBObjectStore(args.couchdb_url, args.database)
    dirs = sorted(path for path in args.root.iterdir() if path.is_dir())
    if args.limit:
        dirs = dirs[:args.limit]
    results = [verify_dir(store, path) for path in dirs]
    failed = [row for row in results if not row["ok"]]
    print(json.dumps({
        "checked": len(results), "failed": len(failed), "failures": failed[:10],
    }, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
