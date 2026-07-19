"""Serialization helpers for point-in-time data availability profiles."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def utc_iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat()


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def profile_document(
    *,
    product_scope: list[str],
    entries: list[dict[str, Any]],
    as_of: datetime,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": 1,
        "as_of": utc_iso(as_of),
        "product_scope": product_scope,
        "entries": entries,
    }
    return {**body, "profile_hash": canonical_hash(body)}
