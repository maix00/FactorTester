"""Opaque object-reference codecs owned by object adapters."""

from __future__ import annotations


def research_object_id(publication_id: str, item_id: str) -> str:
    publication = str(publication_id or "").strip()
    item = str(item_id or "").strip()
    if not publication or not item or ":" in publication:
        raise ValueError("research object identity is invalid")
    return f"{publication}:{item}"


def split_research_object_id(value: str) -> tuple[str, str]:
    publication, separator, item = str(value or "").partition(":")
    if not separator or not publication or not item:
        raise ValueError("research object identity is invalid")
    return publication, item


__all__ = ["research_object_id", "split_research_object_id"]
