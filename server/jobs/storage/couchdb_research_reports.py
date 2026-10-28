"""CouchDB-backed authored Research Reports (distinct from Job test reports)."""

from __future__ import annotations

from typing import Any

REF_PREFIX = "research-report:"


def document_id(publication_id: str) -> str:
    return REF_PREFIX + str(publication_id)


def get_research_report(store, publication_id: str) -> dict[str, Any]:
    import json

    status, body = store._request("GET", document_id(publication_id))
    if status != 200:
        raise FileNotFoundError(publication_id)
    document = json.loads(body)
    if document.get("kind") != "research_report":
        raise ValueError("not a research report")
    return document


def projection(store, document: dict[str, Any]) -> dict[str, Any]:
    """Load the report projection saved as ``projection.json``."""
    import json

    meta = (document.get("attachments") or {}).get("projection.json") or {}
    name = str(meta.get("name") or "")
    if not name:
        raise FileNotFoundError("projection attachment is missing")
    return json.loads(store.get_attachment(document["_id"], name))
