#!/usr/bin/env python3
"""Materialize one CouchDB Research Report into agent-readable local files."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publication-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--couchdb-url", default="http://admin:secret@127.0.0.1:5984")
    parser.add_argument("--database", default="ft_objects")
    parser.add_argument("--download-attachments", action="store_true")
    args = parser.parse_args(argv)
    parsed = urllib.parse.urlsplit(args.couchdb_url)
    auth = "Basic " + base64.b64encode(
        f"{parsed.username}:{parsed.password or ''}".encode()).decode()
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc += f":{parsed.port}"
    base = f"{parsed.scheme or 'http'}://{netloc}/{urllib.parse.quote(args.database)}"

    def get(path: str) -> bytes:
        request = urllib.request.Request(base + "/" + path,
                                         headers={"Authorization": auth})
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()

    doc_id = urllib.parse.quote("research-report:" + args.publication_id)
    document = json.loads(get(doc_id))
    attachments = document.get("attachments") or {}
    meta = attachments.get("projection.json") or {}
    projection = json.loads(get(f"{doc_id}/{urllib.parse.quote(meta['name'])}"))
    index_meta = attachments.get("index.json") or {}
    index = json.loads(get(f"{doc_id}/{urllib.parse.quote(index_meta['name'])}"))
    args.output.mkdir(parents=True, exist_ok=True)
    lines = [f"# {document.get('title') or index.get('title') or projection.get('title') or ''}", ""]
    chapters = []
    for chapter in index.get("chapters") or []:
        chapter_id = str(chapter.get("component_id") or "")
        digest = hashlib.sha256(chapter_id.encode()).hexdigest()[:32]
        chapter_meta = attachments.get(f"chapters/{digest}.json") or {}
        name = str(chapter_meta.get("name") or "")
        if not name:
            continue
        chapter_doc = json.loads(get(f"{doc_id}/{urllib.parse.quote(name)}"))
        chapters.append({"chapter_id": chapter_id, "title": chapter_doc.get("title") or chapter.get("title") or "",
                         "path": f"chapters/{digest}.json", "attachment": name})
        lines.extend([f"# {chapter_doc.get('title') or chapter.get('title') or ''}", ""])
        for component in chapter_doc.get("components") or []:
            body = str(component.get("body") or "").strip()
            title = str(component.get("title") or "").strip()
            if title and body:
                lines.extend([f"## {title}", "", body, ""])
            elif body:
                lines.extend([body, ""])
    (args.output / "manifest.json").write_text(json.dumps({
        "report": {"publication_id": args.publication_id,
                   "title": document.get("title"), "owner_ref": document.get("owner_ref"),
                   "projection_hash": document.get("projection_hash")},
        "chapters": chapters,
        "attachments": [{"path": path, **value} for path, value in sorted(attachments.items())],
    }, ensure_ascii=False, indent=2))
    (args.output / "report.md").write_text("\n".join(lines).rstrip() + "\n")
    if args.download_attachments:
        target = args.output / "files"
        target.mkdir(exist_ok=True)
        for path, value in sorted(attachments.items()):
            name = str((value or {}).get("name") or "")
            if not name:
                continue
            data = get(f"{doc_id}/{urllib.parse.quote(name)}")
            file = target / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
    print(json.dumps({"markdown": str(args.output / "report.md"),
                      "manifest": str(args.output / "manifest.json"),
                      "chapters": len(chapters),
                      "attachments": len(attachments)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
