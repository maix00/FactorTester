#!/usr/bin/env python3
"""Migrate authored Research Reports (public-research mirrors) into CouchDB.

This is distinct from Job test reports.  It reads publications.json plus the
mirror directory and writes one ``research_report`` document per publication,
with content-addressed attachments.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DOC_PREFIX = "research-report:"


def attachment_name(path: Path, data: bytes) -> str:
    suffix = "".join(path.suffixes[-2:]) if path.suffixes else ""
    return f"{hashlib.sha256(data).hexdigest()}{suffix.lower()}"


def doc_for_record(record: dict) -> dict:
    publication_id = str(record.get("publication_id") or "")
    if not publication_id:
        raise ValueError("publication_id is required")
    return {
        "_id": DOC_PREFIX + publication_id,
        "schema_version": 1,
        "kind": "research_report",
        "publication_id": publication_id,
        "report_id": str(record.get("report_id") or ""),
        "owner_ref": str(record.get("owner_ref") or ""),
        "title": str(record.get("title") or ""),
        "visibility": str(record.get("visibility") or "private"),
        "branch_ref": str(record.get("branch_ref") or ""),
        "profile_ref": str(record.get("profile_ref") or ""),
        "projection_hash": str(record.get("projection_hash") or ""),
        "published_at": record.get("published_at"),
        "publication": record,
        "attachments": {},
    }


def _request(url: str, *, method="GET", body=None, content_type="application/json",
             timeout=60, auth: str = "") -> tuple[int, bytes, dict]:
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    if auth:
        headers["Authorization"] = auth
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def _json_request(url: str, **kwargs):
    status, raw, headers = _request(url, **kwargs)
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {"raw": raw.decode("utf-8", "replace")}
    return status, payload


def migrate(root: Path, couchdb_url: str, database: str, *, dry_run: bool,
            limit: int = 0, owner: str = "") -> dict:
    registry = json.loads((root / "publications.json").read_text())
    publications = list(registry.get("publications") or [])
    if owner:
        publications = [item for item in publications if item.get("owner_ref") == owner]
    if limit:
        publications = publications[:limit]
    parsed = urllib.parse.urlsplit(couchdb_url)
    auth = ""
    if parsed.username is not None:
        auth = "Basic " + base64.b64encode(
            f"{urllib.parse.unquote(parsed.username)}:{urllib.parse.unquote(parsed.password or '')}".encode()
        ).decode()
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc += f":{parsed.port}"
    base = f"{parsed.scheme or 'http'}://{netloc}/{urllib.parse.quote(database)}"
    migrated, skipped, failed, attachments = [], [], [], 0
    for record in publications:
        publication_id = str(record.get("publication_id") or "")
        if not publication_id:
            continue
        doc = doc_for_record(record)
        if dry_run:
            migrated.append(publication_id)
            continue
        status, payload = _json_request(f"{base}/{urllib.parse.quote(doc['_id'])}", method="PUT",
                                        body=json.dumps(doc).encode(), auth=auth)
        if status == 409:
            skipped.append(publication_id)
            continue
        if status not in {201, 202}:
            failed.append({"id": publication_id, "status": status, "error": payload})
            continue
        revision = str(payload.get("rev") or "")
        mirror = root / "mirrors" / publication_id
        if mirror.is_dir():
            for path in sorted(mirror.rglob("*")):
                if path.is_symlink() or not path.is_file() or path.name == ".DS_Store":
                    continue
                data = path.read_bytes()
                name = attachment_name(path, data)
                relative = path.relative_to(mirror).as_posix()
                if relative in doc["attachments"]:
                    continue
                encoded = urllib.parse.quote(name)
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                status, payload = _json_request(
                    f"{base}/{urllib.parse.quote(doc['_id'])}/{encoded}?rev={revision}",
                    method="PUT", body=data, content_type=content_type, auth=auth,
                )
                if status not in {201, 202}:
                    failed.append({"id": publication_id, "attachment": relative,
                                   "status": status, "error": payload})
                    continue
                revision = str(payload.get("rev") or revision)
                doc["attachments"][relative] = {"name": name, "content_type": content_type,
                                                "size_bytes": len(data)}
                attachments += 1
            status, payload = _json_request(
                f"{base}/{urllib.parse.quote(doc['_id'])}?rev={revision}",
                method="PUT", body=json.dumps(doc).encode(), auth=auth,
            )
            if status not in {201, 202}:
                failed.append({"id": publication_id, "final": status, "error": payload})
                continue
        migrated.append(publication_id)
    return {"migrated": len(migrated), "skipped": len(skipped), "failed": len(failed),
            "attachments": attachments, "ids": migrated, "errors": failed[:20]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/data/public-research"))
    parser.add_argument("--couchdb-url", default="http://admin:secret@127.0.0.1:5984")
    parser.add_argument("--database", default="ft_objects")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--owner", default="")
    args = parser.parse_args(argv)
    result = migrate(args.root, args.couchdb_url, args.database,
                     dry_run=args.dry_run, limit=args.limit, owner=args.owner)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
