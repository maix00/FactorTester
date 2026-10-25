#!/usr/bin/env python3
"""Read-only readiness report for switching to CouchDB authority."""

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
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--couchdb-url", required=True)
    parser.add_argument("--database", default="ft_objects")
    args = parser.parse_args(argv)
    parsed = urllib.parse.urlsplit(args.couchdb_url)
    auth = "Basic " + base64.b64encode(
        f"{parsed.username}:{parsed.password or ''}".encode()).decode()
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    base = f"{parsed.scheme or 'http'}://{host}/{args.database}"

    def rows(prefix: str) -> dict[str, dict]:
        url = (f"{base}/_all_docs?include_docs=true&startkey="
               f"{urllib.parse.quote(json.dumps(prefix))}&endkey="
               f"{urllib.parse.quote(json.dumps(prefix + chr(0x10FFFF)))}")
        request = urllib.request.Request(url, headers={"Authorization": auth})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
        return {item["id"]: item.get("doc") or {} for item in payload.get("rows") or []}

    with sqlite3.connect(args.db) as conn:
        conn.row_factory = sqlite3.Row
        factors = conn.execute("SELECT source_kind, owner_username, factor_id FROM factor_family_catalog").fetchall()
        heads = conn.execute("SELECT principal, entity_id FROM account_domain_entities WHERE entity_type='factor_family'").fetchall()
        groups = conn.execute("SELECT username, group_name, payload_json FROM account_product_groups").fetchall()
        strategies = conn.execute("SELECT strategy_ref FROM strategy_library_entries WHERE deleted_at=0").fetchall()

    couch_factors = rows("factor-family:")
    couch_heads = rows("factor-family-head:")
    couch_groups = rows("product-group:")
    couch_strategies = rows("strategy_version:")
    couch_reports = rows("research-report:")

    expected_factors = {
        f"factor-family:{row['owner_username'] or 'public'}:{row['factor_id']}"
        for row in factors
    }
    expected_groups = set()
    for row in groups:
        payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
        group_id = str(payload.get("id") or row["group_name"])
        expected_groups.add(f"product-group:{row['username']}:{group_id}")
    report = {
        "factors": {"sqlite": len(expected_factors), "couch": len(couch_factors),
                    "missing": sorted(expected_factors - set(couch_factors))[:20]},
        "factor_heads": {"sqlite": len(heads), "couch": len(couch_heads)},
        "product_groups": {"sqlite": len(expected_groups), "couch": len(couch_groups),
                           "missing": sorted(expected_groups - set(couch_groups))[:20]},
        "strategies": {"sqlite": len(strategies), "couch": len(couch_strategies)},
        "research_reports": {"couch": len(couch_reports)},
    }
    report["ready"] = not report["factors"]["missing"] and not report["product_groups"]["missing"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
