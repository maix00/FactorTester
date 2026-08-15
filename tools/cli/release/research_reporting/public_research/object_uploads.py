"""Detach publication bytes before the projection crosses the control plane."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ResearchObjectUpload:
    """One bounded object body that must be sent through Manager 7997."""

    object_kind: str
    object_id: str
    filename: str
    content_type: str
    content_hash: str
    content: bytes

    @property
    def size_bytes(self) -> int:
        return len(self.content)


def detach_object_bytes(
    projection: dict[str, Any],
) -> tuple[dict[str, Any], tuple[ResearchObjectUpload, ...]]:
    """Return a source-free projection and its separately streamed objects.

    Older clients may still send ``content_base64`` in the projection and the
    library continues to accept that format.  New publication clients call
    this seam first, so the 7998 request contains only metadata and every
    object body is transferred with a short-lived 7997 upload capability.
    """
    metadata = dict(projection)
    uploads: list[ResearchObjectUpload] = []
    collections = (
        ("assets", "research_asset", "asset_id"),
        ("attachments", "research_attachment", "attachment_ref"),
        ("local_resources", "research_local_resource", "resource_id"),
    )
    for collection_name, object_kind, id_key in collections:
        clean_items: list[dict[str, Any]] = []
        for raw_item in projection.get(collection_name) or []:
            if not isinstance(raw_item, dict):
                continue
            item = dict(raw_item)
            encoded = item.pop("content_base64", None)
            if encoded is not None:
                try:
                    content = base64.b64decode(str(encoded), validate=True)
                except (ValueError, TypeError) as exc:
                    raise ValueError(
                        f"{object_kind} content_base64 is invalid"
                    ) from exc
                digest = hashlib.sha256(content).hexdigest()
                declared = str(item.get("content_hash") or "").strip().lower()
                if declared and declared != digest:
                    raise ValueError(f"{object_kind} content hash mismatch")
                item["content_hash"] = declared or digest
                item["size_bytes"] = len(content)
                uploads.append(ResearchObjectUpload(
                    object_kind=object_kind,
                    object_id=str(item.get(id_key) or "").strip(),
                    filename=str(item.get("filename") or "object").strip()
                    or "object",
                    content_type=str(
                        item.get("media_type") or "application/octet-stream"
                    ).strip() or "application/octet-stream",
                    content_hash=digest,
                    content=content,
                ))
            clean_items.append(item)
        metadata[collection_name] = clean_items
    metadata["projection_hash"] = projection_hash(metadata)
    return metadata, tuple(uploads)


def projection_hash(projection: dict[str, Any]) -> str:
    """Hash the exact source-free projection sent to Manager 7998."""
    return hashlib.sha256(json.dumps(
        {
            key: value
            for key, value in projection.items()
            if key != "projection_hash"
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


__all__ = [
    "ResearchObjectUpload", "detach_object_bytes", "projection_hash",
]
