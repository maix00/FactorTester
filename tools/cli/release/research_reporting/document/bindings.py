"""External object bindings kept outside content-only report documents."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any
from pathlib import Path

from .model import document_hash
from .validation import identifier, reference, text, validate_document

SCHEMA_VERSION = 1
MAX_BINDINGS = 4096
MAX_BINDING_DATA_BYTES = 64 * 1024
_KINDS = {
    "evidence", "obligation", "task", "job", "claim", "artifact",
    "report_requirement", "graph_reference", "checkpoint", "run",
}
_FIELDS = {
    "schema_version", "document_id", "document_hash", "bindings",
    "migration",
}
_BINDING_FIELDS = {
    "binding_id", "component_id", "kind", "target_ref", "label", "data",
}


def bindings_path_for(document_path: str | Path) -> Path:
    """Return the adjacent binding file used by all CLI surfaces."""
    path = Path(document_path)
    return path.with_suffix(path.suffix + ".bindings.json")


def new_bindings(document: dict[str, Any]) -> dict[str, Any]:
    value = validate_document(document)
    return {
        "schema_version": SCHEMA_VERSION,
        "document_id": value["document_id"],
        "document_hash": document_hash(value),
        "bindings": [],
        "migration": None,
    }


def add_binding(
    bindings: dict[str, Any], document: dict[str, Any], *,
    component_id: str, binding_id: str, kind: str, target_ref: str,
    label: str = "", data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document_value = validate_document(document)
    candidate = deepcopy(bindings)
    # A content component may have been added immediately before this binding.
    # Synchronize the pair at the mutation boundary; save_bindings remains
    # strict and never persists a stale document hash.
    candidate["document_hash"] = document_hash(document_value)
    value = validate_bindings(candidate, document_value)
    component_ids = {item["component_id"] for item in document_value["components"]}
    identifier(component_id, "binding.component_id")
    if component_id not in component_ids:
        raise ValueError("binding component_id does not exist")
    identifier(binding_id, "binding_id")
    if kind not in _KINDS:
        raise ValueError(f"unknown report binding kind: {kind}")
    reference(target_ref, "binding.target_ref")
    text(label, "binding.label", allow_empty=True, maximum=256)
    if data is not None and not isinstance(data, dict):
        raise ValueError("binding data must be an object")
    if any(item["binding_id"] == binding_id for item in value["bindings"]):
        raise ValueError("binding_id already exists")
    value["bindings"].append({
        "binding_id": binding_id,
        "component_id": component_id,
        "kind": kind,
        "target_ref": target_ref,
        "label": label,
        "data": deepcopy(data or {}),
    })
    value["document_hash"] = document_hash(document_value)
    return validate_bindings(value, document_value)


def validate_bindings(
    value: Any, document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("report bindings must use the v1 schema")
    result = deepcopy(value)
    identifier(result.get("document_id"), "bindings.document_id")
    declared_hash = result.get("document_hash")
    if not isinstance(declared_hash, str) or len(declared_hash) != 64:
        raise ValueError("bindings.document_hash must be sha256")
    if document is not None:
        document_value = validate_document(document)
        if result["document_id"] != document_value["document_id"]:
            raise ValueError("bindings document_id does not match document")
        if result["document_hash"] != document_hash(document_value):
            raise ValueError("bindings document_hash does not match document")
        component_ids = {item["component_id"] for item in document_value["components"]}
    else:
        component_ids = None
    if result.get("migration") is not None and not isinstance(result["migration"], dict):
        raise ValueError("bindings.migration must be an object or null")
    bindings = result.get("bindings")
    if not isinstance(bindings, list) or len(bindings) > MAX_BINDINGS:
        raise ValueError("bindings.bindings must be an array")
    ids: set[str] = set()
    for item in bindings:
        if not isinstance(item, dict) or set(item) != _BINDING_FIELDS:
            raise ValueError("report binding fields are invalid")
        identifier(item.get("binding_id"), "binding.binding_id")
        if item["binding_id"] in ids:
            raise ValueError("duplicate binding_id")
        ids.add(item["binding_id"])
        identifier(item.get("component_id"), "binding.component_id")
        if component_ids is not None and item["component_id"] not in component_ids:
            raise ValueError("binding component_id is unknown")
        if item.get("kind") not in _KINDS:
            raise ValueError("report binding kind is invalid")
        reference(item.get("target_ref"), "binding.target_ref")
        text(item.get("label"), "binding.label", allow_empty=True, maximum=256)
        if not isinstance(item.get("data"), dict):
            raise ValueError("binding data must be an object")
        try:
            encoded = json.dumps(
                item["data"], ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("binding data must be JSON-compatible") from exc
        if len(encoded) > MAX_BINDING_DATA_BYTES:
            raise ValueError(
                f"binding data exceeds {MAX_BINDING_DATA_BYTES} bytes"
            )
    return result


def bindings_hash(bindings: dict[str, Any]) -> str:
    value = validate_bindings(bindings)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def bindings_manifest(
    bindings: dict[str, Any], document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = validate_bindings(bindings, document)
    return {
        "schema_version": SCHEMA_VERSION,
        "document_id": value["document_id"],
        "document_hash": value["document_hash"],
        "bindings_hash": bindings_hash(value),
        "binding_refs": [
            {
                "binding_id": item["binding_id"],
                "component_id": item["component_id"],
                "kind": item["kind"],
                "target_ref": item["target_ref"],
            }
            for item in value["bindings"]
        ],
    }


def rebind_document(
    bindings: dict[str, Any], document: dict[str, Any],
) -> dict[str, Any]:
    """Update only the document identity after a content mutation."""
    value = validate_document(document)
    candidate = deepcopy(bindings)
    candidate["document_id"] = value["document_id"]
    candidate["document_hash"] = document_hash(value)
    return validate_bindings(candidate, value)
