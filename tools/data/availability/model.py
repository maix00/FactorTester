"""Serialization helpers for source-scoped availability observations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


PROFILE_SCHEMA_VERSION = 4


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
    source_scope: list[str] | None = None,
    frequency_scope: list[str] | None = None,
    probe: bool | None = None,
    expanded: bool | None = None,
    required_fields: list[str] | None = None,
    include_field_catalog: bool | None = None,
    include_historical_fields: bool | None = None,
    historical_fields: list[dict[str, Any]] | None = None,
    inspection_runtime: str | None = None,
) -> dict[str, Any]:
    request_bound = source_scope is not None
    body: dict[str, Any] = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "as_of": utc_iso(as_of),
        "product_scope": product_scope,
        "entries": entries,
    }
    if request_bound:
        body.update({
            "source_scope": list(source_scope or []),
            "frequency_scope": list(frequency_scope or []),
            "probe": bool(probe),
            "expanded": bool(expanded),
        })
        if required_fields is not None:
            body["required_fields"] = list(required_fields)
        if include_field_catalog is not None:
            body["include_field_catalog"] = bool(include_field_catalog)
        if include_historical_fields is not None:
            body["include_historical_fields"] = bool(include_historical_fields)
        if historical_fields is not None:
            body["historical_fields"] = historical_fields
        if inspection_runtime is not None:
            body["inspection_runtime"] = str(inspection_runtime)
    return {**body, "profile_hash": canonical_hash(body)}
