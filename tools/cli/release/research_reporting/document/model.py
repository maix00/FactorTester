"""Immutable-style updates for content-only research reports."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from .content import component_content
from .validation import KINDS, identifier, reference, text, validate_document


def new_document(
    document_id: str, title: str, *, language: str = "zh-Hans",
) -> dict[str, Any]:
    identifier(document_id, "document_id")
    text(title, "title")
    return {
        "schema_version": 2,
        "document_id": document_id,
        "title": title,
        "language": language,
        "revision": 0,
        "components": [],
        "assets": [],
    }


def add_component(
    document: dict[str, Any], *, component_id: str, kind: str, title: str,
    parent_id: str | None = None, body: str = "", content: Any = None,
    display_kind: str = "",
) -> dict[str, Any]:
    result = validate_document(document)
    identifier(component_id, "component_id")
    if kind not in KINDS:
        raise ValueError(f"unsupported report component kind: {kind}")
    text(title, "component.title")
    if not isinstance(display_kind, str) or len(display_kind.encode()) > 128:
        raise ValueError("component.display_kind is invalid")
    if kind == "special" and not display_kind.strip():
        raise ValueError("special component requires display_kind")
    if parent_id is not None:
        identifier(parent_id, "parent_id")
        if not any(item["component_id"] == parent_id for item in result["components"]):
            raise ValueError("parent component does not exist")
    if any(item["component_id"] == component_id for item in result["components"]):
        raise ValueError("component_id already exists")
    component_content(kind, content)
    result["components"].append({
        "component_id": component_id,
        "kind": kind,
        "parent_id": parent_id,
        "title": title,
        "body": text(body, "component.body", allow_empty=True),
        "content": content,
        "display_kind": display_kind,
        "created_at": time.time(),
    })
    result["revision"] += 1
    return validate_document(result)


def add_asset(document: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    result = validate_document(document)
    if not isinstance(asset, dict):
        raise ValueError("asset must be an object")
    normalized = {
        "asset_ref": asset.get("asset_ref"),
        "media_type": asset.get("media_type"),
        "filename": asset.get("filename"),
        "caption": asset.get("caption") or "",
        "alt_text": asset.get("alt_text") or "",
    }
    reference(normalized["asset_ref"], "asset.asset_ref")
    if any(item["asset_ref"] == normalized["asset_ref"] for item in result["assets"]):
        raise ValueError("asset_ref already exists")
    result["assets"].append(normalized)
    result["revision"] += 1
    return validate_document(result)


def document_hash(document: dict[str, Any]) -> str:
    value = validate_document(document)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
