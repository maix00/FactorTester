#!/usr/bin/env python3
"""Verify migrated Research Report documents and attachment metadata."""

from __future__ import annotations

import argparse
import base64
import json
import urllib.parse
import urllib.request
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/data/public-research"))
    parser.add_argument("--couchdb-url", default="http://admin:secret@127.0.0.1:5984")
    parser.add_argument("--database", default="ft_objects")
    args = parser.parse_args(argv)
    parsed = urllib.parse.urlsplit(args.couchdb_url)
    auth = ""
    if parsed.username is not None:
        auth = "Basic " + base64.b64encode(
            f"{parsed.username}:{parsed.password or ''}".encode()
        ).decode()
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc += f":{parsed.port}"
    base = f"{parsed.scheme or 'http'}://{netloc}/{args.database}"
    records = json.loads((args.root / "publications.json").read_text()).get("publications") or []
    missing, no_attachments, mismatches = [], [], []
    for record in records:
        publication_id = str(record.get("publication_id") or "")
        if not publication_id:
            continue
        request = urllib.request.Request(
            f"{base}/{urllib.parse.quote('research-report:' + publication_id)}",
            headers={"Authorization": auth},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                document = json.loads(response.read())
        except Exception:
            missing.append(publication_id)
            continue
        if document.get("kind") != "research_report" or not document.get("attachments"):
            no_attachments.append(publication_id)
        publication = document.get("publication") or {}
        for field in ("title", "owner_ref", "visibility", "projection_hash"):
            if str(publication.get(field) or "") != str(record.get(field) or ""):
                mismatches.append({"publication_id": publication_id, "field": field})
        mirror = args.root / "mirrors" / publication_id
        if mirror.is_dir():
            files = [path for path in mirror.rglob("*")
                     if path.is_file() and not path.is_symlink() and path.name != ".DS_Store"]
            stored = document.get("attachments") or {}
            if len(files) != len(stored):
                mismatches.append({"publication_id": publication_id,
                                   "files": len(files), "attachments": len(stored)})
    print(json.dumps({
        "checked": len(records), "missing": missing,
        "without_attachments": no_attachments, "mismatches": mismatches,
    }, indent=2))
    return 1 if missing or mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
