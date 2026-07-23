"""Canonical hashes shared by report preparation and local publication."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def report_item_hash(
    *,
    report_requirement_id: str,
    subject_ref: str,
    content_kind: str,
    content: dict[str, Any],
) -> str:
    return _hash({
        "report_requirement_id": report_requirement_id,
        "subject_ref": subject_ref,
        "content_kind": content_kind,
        "content": content,
    })


def report_fragment_hash(items: list[dict[str, str]]) -> str:
    projected = [
        {
            "report_requirement_id": str(item["report_requirement_id"]),
            "subject_ref": str(item["subject_ref"]),
            "content_kind": str(item["content_kind"]),
            "item_hash": str(item["item_hash"]),
        }
        for item in items
    ]
    projected.sort(key=lambda item: (
        item["report_requirement_id"], item["subject_ref"]
    ))
    return _hash(projected)


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
