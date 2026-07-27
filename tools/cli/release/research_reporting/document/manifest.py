"""Reference-only receipts for graph-independent report documents."""

from __future__ import annotations

from typing import Any

from .model import document_hash
from .validation import validate_document


def document_manifest(document: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded receipt without copying report content.

    The manifest is safe to place beside a Graph navigation packet or a local
    command receipt.  It deliberately omits component bodies, content, chip
    data, metadata, and asset bytes; the document file remains the content
    owner.
    """
    value = validate_document(document)
    return {
        "schema_version": 2,
        "document_id": value["document_id"],
        "revision": value["revision"],
        "language": value["language"],
        "document_hash": document_hash(value),
        "component_refs": [
            {
                "component_id": item["component_id"],
                "kind": item["kind"],
                "parent_id": item["parent_id"],
            }
            for item in value["components"]
        ],
        "asset_refs": [
            {
                "asset_ref": item["asset_ref"],
                "media_type": item["media_type"],
                "filename": item["filename"],
            }
            for item in value["assets"]
        ],
    }
