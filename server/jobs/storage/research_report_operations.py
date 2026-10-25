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


def move_component(chapter: dict[str, Any], component_id: str, parent_id: str,
                   after_component_id: str) -> dict[str, Any]:
    components = list(chapter.get("components") or [])
    by_id = {str(item.get("component_id") or ""): item for item in components}
    if component_id not in by_id:
        raise ValueError("component not found")
    if parent_id not in by_id:
        raise ValueError("parent not found")
    if after_component_id not in by_id:
        raise ValueError("after component not found")
    if component_id == parent_id:
        raise ValueError("component cannot be its own parent")
    parent = by_id[parent_id]
    child = dict(by_id[component_id])
    if str(child.get("kind") or "") == "chapter":
        raise ValueError("chapter root cannot be moved as a component")
    cursor = parent_id
    seen = set()
    while cursor:
        if cursor in seen:
            raise ValueError("cycle detected")
        seen.add(cursor)
        if cursor == component_id:
            raise ValueError("move would create a cycle")
        cursor = str((by_id.get(cursor) or {}).get("parent_id") or "")
    components = [item for item in components if str(item.get("component_id")) != component_id]
    child["parent_id"] = parent_id
    target_index = next(index for index, item in enumerate(components)
                        if str(item.get("component_id")) == after_component_id)
    components.insert(target_index + 1, child)
    return {**chapter, "components": components}


def apply_component_move(store, document: dict[str, Any], *, base_rev: str,
                         chapter_id: str, component_id: str, parent_id: str,
                         after_component_id: str) -> dict[str, Any]:
    if str(document.get("_rev") or "") != str(base_rev or ""):
        raise ValueError("revision conflict")
    logical = chapter_attachment_path(chapter_id)
    meta = (document.get("attachments") or {}).get(logical) or {}
    name = str(meta.get("name") or "")
    if not name:
        raise ValueError("chapter attachment is missing")
    chapter = json.loads(store.get_attachment(str(document["_id"]), name))
    chapter = move_component(chapter, component_id, parent_id, after_component_id)
    raw = json.dumps(chapter, ensure_ascii=False, sort_keys=True).encode()
    new_name = hashlib.sha256(raw).hexdigest() + ".json"
    try:
        status, body = store._request(
            "PUT", f"{document['_id']}/{new_name}?rev={base_rev}", raw,
            content_type="application/json",
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            raise ValueError("revision conflict") from exc
        raise
    if status not in {201, 202}:
        raise ValueError("chapter write failed")
    revision = json.loads(body)["rev"]
    _, fresh_body = store._request("GET", str(document["_id"]))
    fresh = json.loads(fresh_body)
    fresh.setdefault("attachments", {})[logical] = {
        "name": new_name, "content_type": "application/json",
        "size_bytes": len(raw),
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
    return {"rev": json.loads(body)["rev"], "chapter": chapter,
            "attachment": new_name}


from .research_report_agent import chapter_attachment_path
