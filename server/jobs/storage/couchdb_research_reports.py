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
