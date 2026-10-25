#!/usr/bin/env python3
"""Verify factor-family and product-group library rows exist in CouchDB."""

from __future__ import annotations

import argparse
import base64
import json
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("/data/sqlite/unifieddata.sqlite"))
    parser.add_argument("--couchdb-url", default="http://admin:secret@127.0.0.1:5984")
    parser.add_argument("--database", default="ft_objects")
    args = parser.parse_args(argv)
    parsed = urllib.parse.urlsplit(args.couchdb_url)
    auth = "Basic " + base64.b64encode(
        f"{parsed.username}:{parsed.password or ''}".encode()).decode()
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    base = f"{parsed.scheme or 'http'}://{host}/{args.database}"
    with sqlite3.connect(args.db) as conn:
        conn.row_factory = sqlite3.Row
        factors = conn.execute("SELECT owner_username, factor_id FROM factor_family_catalog").fetchall()
        groups = conn.execute("SELECT username, group_name, payload_json FROM account_product_groups").fetchall()
    missing = []
    for row in factors:
        doc_id = f"factor-family:{row['owner_username'] or 'public'}:{row['factor_id']}"
        request = urllib.request.Request(f"{base}/{urllib.parse.quote(doc_id)}",
                                         headers={"Authorization": auth})
        try:
            urllib.request.urlopen(request, timeout=30).read()
        except Exception:
            missing.append(doc_id)
    for row in groups:
        payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
        group_id = str(payload.get("id") or row["group_name"])
        doc_id = f"product-group:{row['username']}:{group_id}"
        request = urllib.request.Request(f"{base}/{urllib.parse.quote(doc_id)}",
                                         headers={"Authorization": auth})
        try:
            urllib.request.urlopen(request, timeout=30).read()
        except Exception:
            missing.append(doc_id)
    print(json.dumps({"factors": len(factors), "product_groups": len(groups),
                      "missing": missing}, indent=2))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
