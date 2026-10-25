#!/usr/bin/env python3
"""Export factor family and product-group library rows into CouchDB."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import base64
import urllib.error
import urllib.parse
import urllib.request


class Store:
    def __init__(self, base_url: str, database: str) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        self.auth = "Basic " + base64.b64encode(
            f"{parsed.username}:{parsed.password or ''}".encode()).decode()
        host = parsed.hostname or ""
        if parsed.port:
            host += f":{parsed.port}"
        self.base = f"{parsed.scheme or 'http'}://{host}/{urllib.parse.quote(database)}"

    def _request(self, method: str, doc_id: str, body: bytes | None = None):
        request = urllib.request.Request(
            f"{self.base}/{urllib.parse.quote(doc_id)}", data=body, method=method,
            headers={"Authorization": self.auth, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


def factor_documents(db: Path) -> list[dict]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM factor_family_catalog").fetchall()
        sources = {(r["source_kind"], r["owner_username"], r["factor_id"]): r["source_code"]
                   for r in conn.execute("SELECT * FROM factor_family_sources")}
        metadata = {(r["source_kind"], r["owner_username"], r["factor_id"]): {
            "chinese_name": r["chinese_name"], "description": r["description"], "category": r["category"],
        } for r in conn.execute("SELECT * FROM factor_family_source_metadata")}
        params: dict[tuple, list] = {}
        for r in conn.execute("SELECT * FROM factor_family_catalog_params ORDER BY param_index"):
            params.setdefault((r["source_kind"], r["owner_username"], r["factor_id"]), []).append({
                "alias": r["alias"], "type": r["type"], "default": r["default_value"],
                "description": r["description"],
            })
    context = lambda row: (row["source_kind"], row["owner_username"], row["factor_id"])
    heads = []
    for r in conn.execute("SELECT principal, entity_id, payload_json, deleted FROM account_domain_entities WHERE entity_type='factor_family'"):
        entity_id = str(r["entity_id"] or "")
        if ":" not in entity_id:
            continue
        kind, factor_id = entity_id.split(":", 1)
        if kind != "factor":
            # source_kind may be custom/public; entity_id prefix is the source kind
            pass
        heads.append({
            "_id": f"factor-family-head:{r['principal']}:{entity_id}",
            "schema_version": 1,
            "kind": "factor_family_head",
            "source_kind": kind,
            "factor_id": factor_id,
            "owner_ref": "" if r["principal"] == "__public__" else r["principal"],
            "deleted": bool(r["deleted"]),
            "payload": json.loads(r["payload_json"]) if r["payload_json"] else {},
        })
    catalog_docs = [{
        "_id": f"factor-family:{row['owner_username'] or 'public'}:{row['factor_id']}",
        "schema_version": 1,
        "kind": "factor_family",
        "source_kind": row["source_kind"],
        "factor_id": row["factor_id"],
        "owner_ref": row["owner_username"] or "",
        "name": row["factor_name"] or "",
        "family": row["factor_family"] or "",
        "is_public": bool(row["is_public"]),
        "catalog": json.loads(row["catalog_json"]) if row["catalog_json"] else {},
        "source_code": sources.get(context(row), ""),
        "metadata": metadata.get(context(row), {}),
        "params": params.get(context(row), []),
        "source_sha256": row["source_sha256"] or "",
    } for row in rows]
    return catalog_docs + heads


def product_group_documents(db: Path) -> list[dict]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM account_product_groups ORDER BY username, sort_index").fetchall()
    documents = []
    for row in rows:
        payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
        group_id = str(payload.get("id") or row["group_name"])
        documents.append({
            "_id": f"product-group:{row['username']}:{group_id}",
            "schema_version": 1,
            "kind": "product_group",
            "owner_ref": row["username"],
            "name": row["group_name"],
            "sort_index": int(row["sort_index"] or 0),
            "payload": payload,
        })
    return documents


def migrate(documents: list[dict], store: Store | None, *, dry_run: bool) -> dict:
    written, skipped, failed = 0, 0, []
    for document in documents:
        if dry_run:
            written += 1
            continue
        status, body = store._request("GET", document["_id"])
        if status == 200:
            current = json.loads(body)
            document["_rev"] = current["_rev"]
        status, body = store._request("PUT", document["_id"], json.dumps(document).encode())
        if status in {201, 202}:
            written += 1
        else:
            failed.append({"id": document["_id"], "status": status,
                           "error": body.decode("utf-8", "replace")[:200]})
    return {"written": written, "failed": len(failed), "errors": failed[:20]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--kind", choices=("factor", "product_group"), required=True)
    parser.add_argument("--couchdb-url", required=True)
    parser.add_argument("--database", default="ft_objects")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    documents = factor_documents(args.db) if args.kind == "factor" else product_group_documents(args.db)
    store = None if args.dry_run else Store(args.couchdb_url, args.database)
    result = migrate(documents, store, dry_run=args.dry_run)
    result["kind"] = args.kind
    result["count"] = len(documents)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
