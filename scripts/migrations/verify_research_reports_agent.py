#!/usr/bin/env python3
"""Verify every migrated Research Report can produce agent Markdown."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import urllib.parse
import urllib.request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--couchdb-url", default="http://admin:secret@127.0.0.1:5984")
    parser.add_argument("--database", default="ft_objects")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    parsed = urllib.parse.urlsplit(args.couchdb_url)
    auth = "Basic " + base64.b64encode(
        f"{parsed.username}:{parsed.password or ''}".encode()).decode()
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    base = f"{parsed.scheme or 'http'}://{host}/{args.database}"

    def get(path: str) -> bytes:
        request = urllib.request.Request(base + "/" + path,
                                         headers={"Authorization": auth})
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()

    rows = json.loads(get(
        "_all_docs?include_docs=true&startkey=%22research-report%3A%22&endkey=%22research-report%3A%EF%BF%B0%22"
    ))["rows"]
    docs = [row["doc"] for row in rows if "doc" in row]
    if args.limit:
        docs = docs[:args.limit]
    failures, empty, characters = [], [], 0
    for document in docs:
        publication_id = str(document.get("publication_id") or "")
        try:
            attachments = document.get("attachments") or {}
            index_meta = attachments.get("index.json") or {}
            index = json.loads(get(
                f"{urllib.parse.quote(document['_id'])}/{urllib.parse.quote(index_meta['name'])}"
            ))
            chapters = 0
            text = []
            for chapter in index.get("chapters") or []:
                digest = hashlib.sha256(str(chapter.get("component_id") or "").encode()).hexdigest()[:32]
                meta = attachments.get(f"chapters/{digest}.json") or {}
                chapter_doc = json.loads(get(
                    f"{urllib.parse.quote(document['_id'])}/{urllib.parse.quote(meta['name'])}"
                ))
                chapters += 1
                for component in chapter_doc.get("components") or []:
                    text.append(str(component.get("body") or ""))
            markdown = "\n".join(text)
            if not chapters:
                raise ValueError("no chapters")
            if not markdown.strip():
                empty.append(publication_id)
            characters += len(markdown)
        except Exception as exc:
            failures.append({"publication_id": publication_id,
                             "error": f"{type(exc).__name__}: {exc}"})
    print(json.dumps({"checked": len(docs), "failed": failures,
                      "empty": empty, "characters": characters},
                     ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
