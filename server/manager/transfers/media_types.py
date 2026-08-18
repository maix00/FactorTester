"""Validation for media types carried by immutable transfer records."""

from __future__ import annotations

import re


DEFAULT_CONTENT_TYPE = "application/octet-stream"
_MEDIA_TYPE = re.compile(
    r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+/[!#$%&'*+.^_`|~0-9A-Za-z-]+$"
)


def normalize_content_type(value: object) -> str:
    """Return a safe HTTP media type, retaining a binary fallback."""

    selected = str(value or "").strip()
    if not selected:
        return DEFAULT_CONTENT_TYPE
    if len(selected) > 255 or "\r" in selected or "\n" in selected:
        raise ValueError("content_type is invalid")
    media_type = selected.split(";", 1)[0].strip()
    if not _MEDIA_TYPE.fullmatch(media_type):
        raise ValueError("content_type is invalid")
    return selected


__all__ = ["DEFAULT_CONTENT_TYPE", "normalize_content_type"]
