"""Validation for report assets referenced by the persistent tree."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .tree_schema import bounded_text, reference


_REQUIRED = {"asset_ref", "media_type", "filename", "caption", "alt_text"}
_OPTIONAL = {"content_hash", "external_ref", "local_ref"}


def validate_asset(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not _REQUIRED.issubset(value):
        raise ValueError("report asset fields are invalid")
    if set(value) - (_REQUIRED | _OPTIONAL):
        raise ValueError("report asset fields are invalid")
    result = deepcopy(value)
    reference(result.get("asset_ref"), "asset.asset_ref")
    bounded_text(result.get("media_type"), "asset.media_type", limit=128)
    bounded_text(result.get("filename"), "asset.filename", limit=512)
    bounded_text(result.get("caption"), "asset.caption", empty=True, limit=512)
    bounded_text(result.get("alt_text"), "asset.alt_text", empty=True, limit=512)
    _validate_local_ref(result.get("local_ref"))
    external_ref = result.get("external_ref")
    if external_ref is not None:
        bounded_text(external_ref, "asset.external_ref", limit=1024)
    content_hash = result.get("content_hash")
    if content_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", content_hash):
        raise ValueError("asset.content_hash must be sha256")
    return result


def _validate_local_ref(value: Any) -> None:
    if value is None:
        return
    if (
        not isinstance(value, str) or not value or value.startswith("/")
        or ".." in value.split("/")
    ):
        raise ValueError("asset.local_ref must be package-relative")
