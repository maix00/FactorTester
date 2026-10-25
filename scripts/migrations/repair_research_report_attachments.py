#!/usr/bin/env python3
"""Re-upload mirror files lost by an earlier metadata-only final PUT."""

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
    base = f"{parsed.scheme or 'http'}://{netloc}/{args.database}"

    def request(method, path, body=None, content_type="application/json"):
        request = urllib.request.Request(
            base + "/" + path, data=body, method=method,
            headers={"Authorization": auth, "Content-Type": content_type})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"{method} {path} -> {exc.code}: {exc.read()[:300]!r}")

    records = json.loads((args.root / "publications.json").read_text()).get("publications") or []
    uploaded, repaired, failed = 0, 0, []
    for record in records:
        publication_id = str(record.get("publication_id") or "")
        if not publication_id:
            continue
        doc_id = urllib.parse.quote(PREFIX + publication_id)
        _, document = request("GET", doc_id)
        attachments = dict(document.get("attachments") or {})
        existing = set((document.get("_attachments") or {}).keys())
        mirror = args.root / "mirrors" / publication_id
        if not mirror.is_dir():
            continue
        for path in sorted(mirror.rglob("*")):
            if path.is_symlink() or not path.is_file() or path.name == ".DS_Store":
                continue
            relative = path.relative_to(mirror).as_posix()
            meta = attachments.get(relative)
            if not meta:
                data = path.read_bytes()
                name = hashlib.sha256(data).hexdigest() + path.suffix.lower()
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                meta = {"name": name, "content_type": content_type, "size_bytes": len(data)}
            name = str(meta.get("name") or "")
            if not name or name in existing:
                continue
            data = path.read_bytes()
            status, payload = request(
                "PUT", f"{doc_id}/{urllib.parse.quote(name)}?rev={document['_rev']}",
                data, str(meta.get("content_type") or "application/octet-stream"))
            if status not in {201, 202}:
                failed.append(f"{publication_id}:{relative}:{status}")
                continue
            uploaded += 1
            document = request("GET", doc_id)[1]
            existing = set((document.get("_attachments") or {}).keys())
            attachments[relative] = meta
        document = request("GET", doc_id)[1]
        document["attachments"] = attachments
        status, _ = request("PUT", f"{doc_id}?rev={document['_rev']}", json.dumps(document).encode())
        if status in {201, 202}:
            repaired += 1
        else:
            failed.append(publication_id)
    print(json.dumps({"repaired": repaired, "uploaded": uploaded,
                      "failed": len(failed), "errors": failed[:20]}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
