"""Validated, revision-checked operations on a CouchDB Research Report index."""

from __future__ import annotations

import hashlib
import json
import urllib.error
from typing import Any


def move_chapter(index: dict[str, Any], chapter_id: str, after_chapter_id: str | None) -> dict[str, Any]:
    chapters = list(index.get("chapters") or [])
    ids = [str(item.get("component_id") or "") for item in chapters]
    if chapter_id not in ids:
        raise ValueError("chapter not found")
    if after_chapter_id is not None and after_chapter_id not in ids:
        raise ValueError("after chapter not found")
    moved = chapters.pop(ids.index(chapter_id))
    if after_chapter_id is None:
        chapters.insert(0, moved)
    else:
        remaining = [str(item.get("component_id") or "") for item in chapters]
        chapters.insert(remaining.index(after_chapter_id) + 1, moved)
    return {**index, "chapters": chapters}


def apply_index_operation(store, document: dict[str, Any], *, base_rev: str,
                          operation: dict[str, Any]) -> dict[str, Any]:
    if str(document.get("_rev") or "") != str(base_rev or ""):
        raise ValueError("revision conflict")
    meta = (document.get("attachments") or {}).get("index.json") or {}
    current_name = str(meta.get("name") or "")
    if not current_name:
        raise ValueError("index attachment is missing")
    index = json.loads(store.get_attachment(str(document["_id"]), current_name))
    op = str(operation.get("op") or "")
    if op == "move_chapter":
        index = move_chapter(index, str(operation.get("chapter_id") or ""),
                             operation.get("after_chapter_id"))
    else:
        raise ValueError("unsupported operation")
    raw = json.dumps(index, ensure_ascii=False, sort_keys=True).encode()
    name = hashlib.sha256(raw).hexdigest() + ".json"
    try:
        status, body = store._request(
            "PUT", f"{document['_id']}/{name}?rev={base_rev}", raw,
            content_type="application/json",
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            raise ValueError("revision conflict") from exc
        raise
    if status not in {201, 202}:
        raise ValueError("index write failed")
    revision = json.loads(body)["rev"]
    fresh_status, fresh_body = store._request("GET", str(document["_id"]))
    fresh = json.loads(fresh_body)
    fresh.setdefault("attachments", {})["index.json"] = {
        "name": name, "content_type": "application/json", "size_bytes": len(raw),
    }
    try:
        status, body = store._request(
            "PUT", f"{document['_id']}?rev={fresh['_rev']}",
            json.dumps(fresh, ensure_ascii=False).encode(), content_type="application/json",
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            raise ValueError("revision conflict") from exc
        raise
    if status not in {201, 202}:
        raise ValueError("document write failed")
    return {"rev": json.loads(body)["rev"], "index": index, "attachment": name}
