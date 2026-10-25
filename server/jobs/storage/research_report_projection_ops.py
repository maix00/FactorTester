"""Projection-aware Research Report edits with CouchDB optimistic concurrency."""

from __future__ import annotations

import hashlib
import json
import urllib.error
from typing import Any

from .research_report_agent import chapter_attachment_path
from .research_report_operations import (
    insert_component, move_component, move_chapter, remove_component,
)


def _hash(payload: dict[str, Any]) -> str:
    value = {key: item for key, item in payload.items() if key != "projection_hash"}
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _attachment(document: dict, logical: str) -> tuple[str, dict]:
    meta = (document.get("attachments") or {}).get(logical) or {}
    name = str(meta.get("name") or "")
    if not name:
        raise ValueError(f"attachment is missing: {logical}")
    return name, meta


def _reorder_chapter_blocks(components: list[dict], chapter_id: str,
                            after_chapter_id: str | None) -> list[dict]:
    indices = [index for index, item in enumerate(components)
               if str(item.get("kind") or "") == "chapter"]
    starts = {str(components[index].get("component_id")): index for index in indices}
    if chapter_id not in starts:
        raise ValueError("chapter not found")
    start = starts[chapter_id]
    later = [index for index in indices if index > start]
    end = later[0] if later else len(components)
    block = components[start:end]
    rest = components[:start] + components[end:]
    if after_chapter_id is None:
        return block + rest
    target_start = next((index for index, item in enumerate(rest)
                         if str(item.get("component_id")) == after_chapter_id), None)
    if target_start is None or str(rest[target_start].get("kind")) != "chapter":
        raise ValueError("after chapter not found")
    later_target = [index for index, item in enumerate(rest)
                    if str(item.get("kind") or "") == "chapter" and index > target_start]
    target_end = later_target[0] if later_target else len(rest)
    return rest[:target_end] + block + rest[target_end:]


def _remove_chapter_block(components: list[dict], chapter_id: str) -> list[dict]:
    starts = [index for index, item in enumerate(components)
              if str(item.get("component_id")) == chapter_id]
    if not starts:
        raise ValueError("chapter not found")
    start = starts[0]
    later = [index for index, item in enumerate(components)
             if index > start and str(item.get("kind") or "") == "chapter"]
    end = later[0] if later else len(components)
    return components[:start] + components[end:]


def _insert_chapter_block(components: list[dict], chapter_id: str,
                          after_chapter_id: str | None) -> list[dict]:
    if any(str(item.get("component_id")) == chapter_id for item in components):
        raise ValueError("chapter already exists")
    block = [{"component_id": chapter_id, "kind": "chapter", "parent_id": None}]
    if after_chapter_id is None:
        return block + components
    indices = [index for index, item in enumerate(components)
               if str(item.get("component_id")) == after_chapter_id]
    if not indices or str(components[indices[0]].get("kind")) != "chapter":
        raise ValueError("after chapter not found")
    start = indices[0]
    later = [index for index, item in enumerate(components)
             if index > start and str(item.get("kind") or "") == "chapter"]
    end = later[0] if later else len(components)
    return components[:end] + block + components[end:]


def _write(store, document: dict, revision: str, logical: str, payload: dict,
           updates: dict[str, dict]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    name = hashlib.sha256(raw).hexdigest() + ".json"
    try:
        status, body = store._request(
            "PUT", f"{document['_id']}/{name}?rev={revision}", raw,
            content_type="application/json",
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            raise ValueError("revision conflict") from exc
        raise
    if status not in {201, 202}:
        raise ValueError("attachment write failed")
    updates[logical] = {"name": name, "content_type": "application/json",
                        "size_bytes": len(raw)}
    return json.loads(body)["rev"]


def _refresh_chapters(store, document: dict, revision: str, projection_hash: str,
                      generation: int, updates: dict[str, dict]) -> str:
    for logical, meta in sorted((document.get("attachments") or {}).items()):
        if not (logical.startswith("chapters/") and logical.endswith(".json")):
            continue
        name = str((updates.get(logical) or {}).get("name") or (meta or {}).get("name") or "")
        if not name:
            continue
        payload = json.loads(store.get_attachment(document["_id"], name))
        payload["projection_hash"] = projection_hash
        payload["generation"] = generation
        revision = _write(store, document, revision, logical, payload, updates)
    return revision


def apply_projection_operation(store, document: dict[str, Any], *, base_rev: str,
                               operation: dict[str, Any]) -> dict[str, Any]:
    if str(document.get("_rev") or "") != str(base_rev or ""):
        raise ValueError("revision conflict")
    projection_name, _ = _attachment(document, "projection.json")
    index_name, _ = _attachment(document, "index.json")
    projection = json.loads(store.get_attachment(document["_id"], projection_name))
    index = json.loads(store.get_attachment(document["_id"], index_name))
    updates: dict[str, dict] = {}
    revision = base_rev
    chapter = None
    op = str(operation.get("op") or "")
    if op == "remove_chapter":
        chapter_id = str(operation.get("chapter_id") or "")
        chapters = list(index.get("chapters") or [])
        filtered = [item for item in chapters
                    if str(item.get("component_id")) != chapter_id]
        if len(filtered) == len(chapters):
            raise ValueError("chapter not found")
        index = {**index, "chapters": filtered}
        projection["components"] = _remove_chapter_block(
            list(projection.get("components") or []), chapter_id)
        removed_logical = chapter_attachment_path(chapter_id)
    elif op == "insert_chapter":
        chapter_id = str(operation.get("chapter_id") or "")
        after = operation.get("after_chapter_id")
        index = move_chapter({
            "chapters": [*index.get("chapters", []),
                         {"component_id": chapter_id,
                          "title": str(operation.get("title") or "")}],
        }, chapter_id, after)
        projection["components"] = _insert_chapter_block(
            list(projection.get("components") or []), chapter_id, after)
        chapter = {"title": str(operation.get("title") or ""),
                   "generation": int(projection.get("generation") or 0) + 1,
                   "components": [{"component_id": chapter_id, "kind": "chapter",
                                   "parent_id": None}]}
    elif op == "move_chapter":
        chapter_id = str(operation.get("chapter_id") or "")
        after = operation.get("after_chapter_id")
        index = move_chapter(index, chapter_id, after)
        projection["components"] = _reorder_chapter_blocks(
            list(projection.get("components") or []), chapter_id, after)
    elif op == "batch":
        operations = list(operation.get("operations") or [])
        chapter_id = str(operations[0].get("chapter_id") or "") if operations else ""
        if not chapter_id:
            raise ValueError("chapter_id is required")
        logical = chapter_attachment_path(chapter_id)
        name, _ = _attachment(document, logical)
        chapter = json.loads(store.get_attachment(document["_id"], name))
        components = list(projection.get("components") or [])
        for item in operations:
            kind = str(item.get("op") or "")
            if kind == "insert_component":
                chapter = insert_component(chapter, dict(item.get("component") or {}),
                                           str(item.get("parent_id") or ""),
                                           str(item.get("after_component_id") or ""))
                components = insert_component({"components": components},
                                              dict(item.get("component") or {}),
                                              str(item.get("parent_id") or ""),
                                              str(item.get("after_component_id") or ""))["components"]
            elif kind == "move_component":
                chapter = move_component(chapter, str(item.get("component_id") or ""),
                                         str(item.get("parent_id") or ""),
                                         str(item.get("after_component_id") or ""))
                components = move_component({"components": components},
                                            str(item.get("component_id") or ""),
                                            str(item.get("parent_id") or ""),
                                            str(item.get("after_component_id") or ""))["components"]
            elif kind == "remove_component":
                chapter = remove_component(chapter, str(item.get("component_id") or ""),
                                           bool(item.get("include_children")))
                components = remove_component({"components": components},
                                              str(item.get("component_id") or ""),
                                              bool(item.get("include_children")))["components"]
            else:
                raise ValueError("unsupported operation")
        projection["components"] = components
        revision = _write(store, document, revision, logical, chapter, updates)
    else:
        chapter_id = str(operation.get("chapter_id") or "")
        logical = chapter_attachment_path(chapter_id)
        name, _ = _attachment(document, logical)
        chapter = json.loads(store.get_attachment(document["_id"], name))
        components = list(projection.get("components") or [])
        if op == "insert_component":
            component = dict(operation.get("component") or {})
            parent = str(operation.get("parent_id") or "")
            after = str(operation.get("after_component_id") or "")
            chapter = insert_component(chapter, component, parent, after)
            components = insert_component({"components": components}, component, parent, after)["components"]
        elif op == "move_component":
            component = str(operation.get("component_id") or "")
            parent = str(operation.get("parent_id") or "")
            after = str(operation.get("after_component_id") or "")
            chapter = move_component(chapter, component, parent, after)
            components = move_component({"components": components}, component, parent, after)["components"]
        elif op == "remove_component":
            component = str(operation.get("component_id") or "")
            include = bool(operation.get("include_children"))
            chapter = remove_component(chapter, component, include)
            components = remove_component({"components": components}, component, include)["components"]
        else:
            raise ValueError("unsupported operation")
        projection["components"] = components
        revision = _write(store, document, revision, logical, chapter, updates)
    generation = int(projection.get("generation") or 0) + 1
    projection["generation"] = generation
    projection["projection_hash"] = _hash(projection)
    index["generation"] = generation
    index["projection_hash"] = projection["projection_hash"]
    if chapter is not None:
        chapter["generation"] = generation
        chapter["projection_hash"] = projection["projection_hash"]
        target_logical = chapter_attachment_path(str(
            operation.get("chapter_id") or
            (operation.get("operations") or [{}])[0].get("chapter_id") or ""
        ))
        if target_logical not in updates:
            updates[target_logical] = {"name": "", "content_type": "application/json",
                                       "size_bytes": 0}
        revision = _write(store, document, revision, target_logical, chapter, updates)
    revision = _write(store, document, revision, "projection.json", projection, updates)
    revision = _write(store, document, revision, "index.json", index, updates)
    revision = _refresh_chapters(store, document, revision,
                                 projection["projection_hash"], generation, updates)
    _, body = store._request("GET", document["_id"])
    fresh = json.loads(body)
    fresh.setdefault("attachments", {}).update(updates)
    if "removed_logical" in locals():
        fresh["attachments"].pop(removed_logical, None)
    fresh["projection_hash"] = projection["projection_hash"]
    fresh["generation"] = generation
    try:
        status, body = store._request(
            "PUT", f"{document['_id']}?rev={fresh['_rev']}",
            json.dumps(fresh, ensure_ascii=False).encode(),
            content_type="application/json",
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            raise ValueError("revision conflict") from exc
        raise
    if status not in {201, 202}:
        raise ValueError("document write failed")
    return {"rev": json.loads(body)["rev"], "projection_hash": projection["projection_hash"],
            "generation": generation, "chapter": chapter}
