#!/usr/bin/env python3
"""Add the projection/index JSON to already-migrated Research Report docs."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import urllib.parse
import urllib.request
from pathlib import Path

PREFIX = "research-report:"


def link(path: Path, data: bytes) -> dict:
    return {"name": hashlib.sha256(data).hexdigest() + path.suffix.lower(),
            "content_type": mimetypes.guess_type(path.name)[0] or "application/json",
            "size_bytes": len(data)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/data/public-research"))
    parser.add_argument("--couchdb-url", default="http://admin:secret@127.0.0.1:5984")
    parser.add_argument("--database", default="ft_objects")
    args = parser.parse_args(argv)
    parsed = urllib.parse.urlsplit(args.couchdb_url)
    auth = "Basic " + base64.b64encode(
        f"{parsed.username}:{parsed.password or ''}".encode()).decode()
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc += f":{parsed.port}"
    base = f"{parsed.scheme or 'http'}://{netloc}/{urllib.parse.quote(args.database)}"

    def request(method, path, body=None, content_type="application/json"):
        req = urllib.request.Request(
            base + "/" + path, data=body, method=method,
            headers={"Authorization": auth, "Content-Type": content_type})
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"{method} {base}/{path} -> {exc.code}: {exc.read()[:300]!r}")

    records = json.loads((args.root / "publications.json").read_text()).get("publications") or []
    updated, skipped, failed = [], [], []
    for record in records:
        publication_id = str(record.get("publication_id") or "")
        if not publication_id:
            continue
        doc_id = urllib.parse.quote(PREFIX + publication_id)
        status, document = request("GET", doc_id)
        if status != 200:
            failed.append(publication_id); continue
        attachments = dict(document.get("attachments") or {})
        if "projection.json" in attachments:
            skipped.append(publication_id); continue
        revision = document["_rev"]
        sources = [
            (args.root / "mirrors" / f"{publication_id}.json", "projection.json"),
            (args.root / "mirrors" / f"{publication_id}.index.json", "index.json"),
        ]
        for path, logical in sources:
            if not path.is_file():
                continue
            data = path.read_bytes()
            meta = link(path, data)
            status, payload = request(
                "PUT", f"{doc_id}/{urllib.parse.quote(meta['name'])}?rev={revision}",
                data, meta["content_type"])
            if status not in {201, 202}:
                failed.append(f"{publication_id}:{logical}"); continue
            revision = payload["rev"]
            attachments[logical] = meta
        _, fresh = request("GET", doc_id)
        fresh["attachments"] = attachments
        status, payload = request("PUT", f"{doc_id}?rev={fresh['_rev']}", json.dumps(fresh).encode())
        if status not in {201, 202}:
            failed.append(publication_id)
        else:
            updated.append(publication_id)
    print(json.dumps({"updated": len(updated), "skipped": len(skipped),
                      "failed": len(failed), "errors": failed[:20]}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
