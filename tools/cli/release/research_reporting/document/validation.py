"""Strict validation for content-only report documents."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from .content import component_content
from .validation_limits import MAX_COMPONENTS, MAX_TEXT

_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SCHEMA_VERSION = 2
KINDS = {
    "chapter", "section", "subsection", "entry", "special", "table",
    "image", "code", "math", "result",
}
_TOP_LEVEL_FIELDS = {
    "schema_version", "document_id", "title", "language", "revision",
    "components", "assets",
}
_COMPONENT_FIELDS = {
    "component_id", "kind", "parent_id", "title", "body", "content",
    "display_kind", "created_at",
}
_ASSET_FIELDS = {
    "asset_ref", "media_type", "filename", "caption", "alt_text",
}


def validate_document(value: Any) -> dict[str, Any]:
    """Validate the new format; old Graph-bound documents are rejected."""
    if not isinstance(value, dict) or set(value) != _TOP_LEVEL_FIELDS:
        raise ValueError("report document must use the content-only v2 schema")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("report document schema_version must be 2")
    result = deepcopy(value)
    identifier(result.get("document_id"), "document_id")
    text(result.get("title"), "title")
    if not isinstance(result.get("language"), str) or not result["language"]:
        raise ValueError("report document language is invalid")
    if type(result.get("revision")) is not int or result["revision"] < 0:
        raise ValueError("report document revision is invalid")
    components = result.get("components")
    if not isinstance(components, list) or len(components) > MAX_COMPONENTS:
        raise ValueError("report document components are invalid")
    ids: set[str] = set()
    for item in components:
        validate_component(item, ids)
    for item in components:
        parent = item["parent_id"]
        if parent is not None and parent not in ids:
            raise ValueError("report component parent_id is unknown")
        if parent == item["component_id"]:
            raise ValueError("report component cannot parent itself")
    assets = result.get("assets")
    if not isinstance(assets, list) or len(assets) > MAX_COMPONENTS:
        raise ValueError("report document assets are invalid")
    asset_ids: set[str] = set()
    for asset in assets:
        validate_asset(asset, asset_ids)
    return result


def validate_component(value: Any, ids: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != _COMPONENT_FIELDS:
        raise ValueError("report component must be a content-only object")
    identifier(value.get("component_id"), "component_id")
    if value["component_id"] in ids:
        raise ValueError("duplicate component_id")
    ids.add(value["component_id"])
    if value.get("kind") not in KINDS:
        raise ValueError("report component kind is invalid")
    parent = value.get("parent_id")
    if parent is not None:
        identifier(parent, "parent_id")
    text(value.get("title"), "component.title")
    text(value.get("body"), "component.body", allow_empty=True)
    display_kind = value.get("display_kind")
    if not isinstance(display_kind, str) or len(display_kind.encode()) > 128:
        raise ValueError("component.display_kind is invalid")
    if value["kind"] == "special" and not display_kind.strip():
        raise ValueError("special component requires display_kind")
    if type(value.get("created_at")) not in {int, float}:
        raise ValueError("component created_at is invalid")
    component_content(value["kind"], value.get("content"))


def validate_asset(value: Any, ids: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != _ASSET_FIELDS:
        raise ValueError("report asset must be a content-only object")
    reference(value.get("asset_ref"), "asset.asset_ref")
    if value["asset_ref"] in ids:
        raise ValueError("duplicate asset_ref")
    ids.add(value["asset_ref"])
    text(value.get("media_type"), "asset.media_type", maximum=128)
    text(value.get("filename"), "asset.filename", maximum=512)
    text(value.get("caption"), "asset.caption", allow_empty=True)
    text(value.get("alt_text"), "asset.alt_text", allow_empty=True)


def identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{field} must be a safe identifier")
    return value


def reference(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value:
        raise ValueError(f"{field} must be a stable local reference")
    if len(value.encode()) > 512:
        raise ValueError(f"{field} is too long")
    return value


def text(
    value: Any, field: str, *, allow_empty: bool = False,
    maximum: int = MAX_TEXT,
) -> str:
    if (
        not isinstance(value, str)
        or (not allow_empty and not value.strip())
        or len(value.encode()) > maximum
    ):
        raise ValueError(f"{field} must be bounded text")
    return value
