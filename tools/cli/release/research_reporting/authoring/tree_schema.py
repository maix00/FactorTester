"""Validation and stable identities for the revisioned report tree."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

from .inline_links import (
    INLINE_LINK_KINDS,
    validate_inline_links,
    validate_typed_target,
)
from .tree_rich_text import validate_rich_text
from .special_kinds import SPECIAL_SECTION_DISPLAY_KINDS


STRUCTURE_NODE_KINDS = ("chapter", "section", "subsection", "special")
CONTENT_NODE_KINDS = ("entry", "list", "table", "image", "code", "math", "result")
NODE_KINDS = set(STRUCTURE_NODE_KINDS + CONTENT_NODE_KINDS)
_CONTENT_KIND_LABELS = {"正文", "表格", "列表", "body", "table", "list"}
BINDING_KINDS = INLINE_LINK_KINDS
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_NODE_FIELDS = {
    "schema_version", "node_id", "kind", "title", "body", "content",
    "display_kind", "created_at", "children", "bindings",
}
_BINDING_FIELDS = {"binding_id", "kind", "target_ref", "label", "data"}
_TABLE_LIMITS = {"rows": 200, "columns": 20, "cells": 5000}

def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} must be a safe identifier")
    return value


def reference(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value:
        raise ValueError(f"{field} must be a stable local reference")
    return value


def node_reference(value: Any) -> str:
    if not isinstance(value, str) or value.startswith("/"):
        raise ValueError("child.ref is invalid")
    parts = value.split("/")
    if len(parts) != 3 or parts[0] != "nodes" or not parts[2].endswith(".json"):
        raise ValueError("child.ref is invalid")
    identifier(parts[1], "child.node_id")
    if len(parts[2]) != 69 or not re.fullmatch(r"[0-9a-f]{64}\.json", parts[2]):
        raise ValueError("child.ref is invalid")
    return value


def bounded_text(value: Any, field: str, *, empty: bool = False, limit: int = 256 * 1024) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f"{field} must be bounded text")
    if len(value.encode("utf-8")) > limit:
        raise ValueError(f"{field} is too large")
    return value


def validate_content(kind: str, value: Any) -> Any:
    if kind == "list":
        _validate_list(value)
    elif kind == "table":
        if (
            not isinstance(value, dict)
            or not {"columns", "rows"}.issubset(value)
            or set(value) - {"columns", "rows", "source", "preview"}
        ):
            raise ValueError(
                "table content must contain columns and rows with optional "
                "source and preview metadata"
            )
        _validate_table_preview(value)
        _validate_table_source(value)
    elif isinstance(value, dict) and {"columns", "rows"}.issubset(value):
        _validate_table_preview(value)
        _validate_table_source(value)
    elif kind == "image":
        if not isinstance(value, dict) or not value.get("asset_ref"):
            raise ValueError("image content requires asset_ref")
    elif kind == "code":
        if not isinstance(value, dict) or set(value) != {"language", "code"}:
            raise ValueError("code content must contain language and code")
    elif kind == "math":
        if not isinstance(value, dict) or set(value) != {"latex", "fallback"}:
            raise ValueError("math content must contain latex and fallback")
        fallback = bounded_text(value["fallback"], "math.fallback", empty=True)
        validate_rich_text(fallback, field="math.fallback")
    elif isinstance(value, str):
        validate_rich_text(value, field="component.content")
    try:
        canonical_bytes(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("component content must be JSON-compatible") from exc
    return deepcopy(value)


def _validate_list(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"style", "items"}:
        raise ValueError("list content must contain style and items")
    if value["style"] not in {"ordered", "unordered"}:
        raise ValueError("list style is invalid")
    items = value["items"]
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise ValueError("list items are invalid")
    for item in items:
        if not isinstance(item, dict) or set(item) != {"text", "depth"}:
            raise ValueError("list item fields are invalid")
        text = bounded_text(item["text"], "list.item", limit=4_096)
        if "\n" in text or "\r" in text:
            raise ValueError("list item must stay on one line")
        validate_inline_links(text, field="list.item")
        if not isinstance(item["depth"], int) or not 0 <= item["depth"] <= 6:
            raise ValueError("list item depth is invalid")


def _validate_table_preview(value: dict[str, Any]) -> None:
    columns, rows = value["columns"], value["rows"]
    if not isinstance(columns, list) or not 1 <= len(columns) <= _TABLE_LIMITS["columns"]:
        raise ValueError("table columns are invalid")
    if not isinstance(rows, list) or len(rows) > _TABLE_LIMITS["rows"]:
        raise ValueError("table rows exceed inline preview limit")
    if len(columns) * len(rows) > _TABLE_LIMITS["cells"]:
        raise ValueError("table cells exceed inline preview limit")
    for column in columns:
        value = bounded_text(column, "table.column", limit=256)
        validate_inline_links(value, field="table.column")
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            raise ValueError("table row width is invalid")
        for cell in row:
            value = bounded_text(cell, "table.cell", empty=True, limit=2048)
            validate_inline_links(value, field="table.cell")


def _validate_table_source(value: dict[str, Any]) -> None:
    source, preview = value.get("source"), value.get("preview")
    if source is None and preview is None:
        return
    if not isinstance(source, dict) or set(source) != {
        "job_id", "artifact_ref", "filename", "content_type", "content_hash",
    }:
        raise ValueError("table source is invalid")
    identifier(source["job_id"], "table.source.job_id")
    reference(source["artifact_ref"], "table.source.artifact_ref")
    filename = source["filename"]
    if not isinstance(filename, str) or "/" in filename or "\\" in filename:
        raise ValueError("table source filename is invalid")
    if not isinstance(source["content_type"], str) or not isinstance(source["content_hash"], str):
        raise ValueError("table source metadata is invalid")
    if not isinstance(preview, dict) or set(preview) != {
        "max_rows", "max_columns", "is_truncated",
    } or not isinstance(preview["is_truncated"], bool):
        raise ValueError("table preview metadata is invalid")


def validate_binding(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _BINDING_FIELDS:
        raise ValueError("report binding fields are invalid")
    result = deepcopy(value)
    identifier(result.get("binding_id"), "binding.binding_id")
    if result.get("kind") not in BINDING_KINDS:
        raise ValueError("report binding kind is invalid")
    validate_typed_target(
        kind=result["kind"], target_ref=result.get("target_ref"),
        field="binding.target_ref",
    )
    bounded_text(result.get("label"), "binding.label", empty=True, limit=256)
    if not isinstance(result.get("data"), dict):
        raise ValueError("binding data must be an object")
    if len(canonical_bytes(result["data"])) > 64 * 1024:
        raise ValueError("binding data is too large")
    return result


def validate_node(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _NODE_FIELDS:
        raise ValueError("report tree node has invalid fields")
    result = deepcopy(value)
    if result.get("schema_version") != 1:
        raise ValueError("report tree node schema_version must be 1")
    identifier(result.get("node_id"), "node_id")
    kind = result.get("kind")
    if kind != "root" and kind not in NODE_KINDS:
        raise ValueError("report tree node kind is invalid")
    title = bounded_text(
        result.get("title"), "node.title",
        empty=kind == "root" or kind in CONTENT_NODE_KINDS,
    )
    if (
        kind in STRUCTURE_NODE_KINDS
        and title.strip().casefold() in _CONTENT_KIND_LABELS
    ):
        raise ValueError(
            "structural report node title must describe its subject, not a "
            "content-kind label"
        )
    if kind == "chapter" and title.startswith("历史检查点 "):
        raise ValueError(
            "chapter title must use the corresponding research node title"
        )
    validate_inline_links(title, field="node.title")
    body = bounded_text(result.get("body"), "node.body", empty=True)
    validate_rich_text(body, field="node.body")
    validate_content("entry" if kind == "root" else kind, result.get("content"))
    bounded_text(result.get("display_kind"), "node.display_kind", empty=True, limit=128)
    if kind == "special" and not result["display_kind"].strip():
        raise ValueError("special node requires display_kind")
    if (
        result["display_kind"] in SPECIAL_SECTION_DISPLAY_KINDS
        and kind != "special"
    ):
        raise ValueError("special display_kind requires a special node")
    if not isinstance(result.get("created_at"), (int, float)):
        raise ValueError("node created_at is invalid")
    children = result.get("children")
    if not isinstance(children, list) or len(children) > 256:
        raise ValueError("node children are invalid")
    seen_children: set[str] = set()
    for child in children:
        if not isinstance(child, dict) or set(child) != {"node_id", "ref"}:
            raise ValueError("child reference is invalid")
        identifier(child["node_id"], "child.node_id")
        if child["node_id"] in seen_children:
            raise ValueError("duplicate child node")
        seen_children.add(child["node_id"])
        node_reference(child["ref"])
    bindings = result.get("bindings")
    if not isinstance(bindings, list) or len(bindings) > 512:
        raise ValueError("node bindings are invalid")
    ids: set[str] = set()
    for binding in bindings:
        item = validate_binding(binding)
        if item["binding_id"] in ids:
            raise ValueError("duplicate binding_id")
        ids.add(item["binding_id"])
    return result
