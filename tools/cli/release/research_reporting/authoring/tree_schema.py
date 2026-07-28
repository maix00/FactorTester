"""Validation and stable identities for the revisioned report tree."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any


NODE_KINDS = {
    "chapter", "section", "subsection", "entry", "special", "table",
    "image", "code", "math", "result",
}
BINDING_KINDS = {
    "evidence", "obligation", "task", "job", "claim", "artifact",
    "report_requirement", "graph_reference", "checkpoint", "run",
}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_NODE_FIELDS = {
    "schema_version", "node_id", "kind", "title", "body", "content",
    "display_kind", "created_at", "children", "bindings",
}
_BINDING_FIELDS = {"binding_id", "kind", "target_ref", "label", "data"}


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
    if kind == "table":
        if not isinstance(value, dict) or set(value) != {"columns", "rows"}:
            raise ValueError("table content must contain columns and rows")
        if not isinstance(value["columns"], list) or not value["columns"]:
            raise ValueError("table columns are invalid")
        if not isinstance(value["rows"], list):
            raise ValueError("table rows are invalid")
    elif kind == "image":
        if not isinstance(value, dict) or not value.get("asset_ref"):
            raise ValueError("image content requires asset_ref")
    elif kind == "code":
        if not isinstance(value, dict) or set(value) != {"language", "code"}:
            raise ValueError("code content must contain language and code")
    elif kind == "math":
        if not isinstance(value, dict) or set(value) != {"latex", "fallback"}:
            raise ValueError("math content must contain latex and fallback")
    try:
        canonical_bytes(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("component content must be JSON-compatible") from exc
    return deepcopy(value)


def validate_binding(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _BINDING_FIELDS:
        raise ValueError("report binding fields are invalid")
    result = deepcopy(value)
    identifier(result.get("binding_id"), "binding.binding_id")
    if result.get("kind") not in BINDING_KINDS:
        raise ValueError("report binding kind is invalid")
    reference(result.get("target_ref"), "binding.target_ref")
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
    bounded_text(result.get("title"), "node.title", empty=kind == "root")
    bounded_text(result.get("body"), "node.body", empty=True)
    validate_content("entry" if kind == "root" else kind, result.get("content"))
    bounded_text(result.get("display_kind"), "node.display_kind", empty=True, limit=128)
    if kind == "special" and not result["display_kind"].strip():
        raise ValueError("special node requires display_kind")
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
