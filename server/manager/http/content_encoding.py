"""Response compression shared by the Manager's HTTP surfaces.

Manager responses are read by a browser on a slow public uplink: the factor
library payload alone is close to a megabyte of JSON, and the Web loads dozens
of module files on a cold visit.  One gzip decision here keeps every surface
(JSON routes, proxy pass-through, static modules, downloads) honest and
consistent: compress only what actually compresses, only when the client asked
for it, and always announce it with ``Vary``.
"""

from __future__ import annotations

import gzip
from typing import Any

# Below this size the framing cost outweighs the saving.
MINIMUM_ENCODED_BYTES = 1024
DEFAULT_LEVEL = 5

_COMPRESSIBLE_MEDIA_TYPES = (
    "application/json",
    "application/javascript",
    "application/xml",
    "application/xhtml+xml",
    "application/x-yaml",
    "image/svg+xml",
)


def accepts_gzip(value: Any) -> bool:
    """Whether an ``Accept-Encoding`` header value allows a gzip response."""
    for item in str(value or "").split(","):
        parts = [part.strip() for part in item.split(";")]
        if not parts or parts[0].lower() != "gzip":
            continue
        quality = next(
            (
                part.split("=", 1)[1].strip()
                for part in parts[1:]
                if part.lower().startswith("q=") and "=" in part
            ),
            "1",
        )
        try:
            return float(quality) > 0
        except ValueError:
            return True
    return False


def is_compressible(content_type: str) -> bool:
    """Whether a media type is worth compressing (text-like, not images)."""
    media_type = str(content_type or "").split(";", 1)[0].strip().lower()
    return media_type.startswith("text/") or media_type in _COMPRESSIBLE_MEDIA_TYPES


def request_accept_encoding(handler: Any) -> str:
    """Read ``Accept-Encoding`` from a duck-typed request handler."""
    headers = getattr(handler, "headers", None)
    reader = getattr(headers, "get", None)
    if not callable(reader):
        return ""
    try:
        return str(reader("Accept-Encoding") or "")
    except Exception:
        return ""


def encode_body(
    raw: bytes,
    content_type: str,
    accept_encoding: Any,
    *,
    minimum_bytes: int = MINIMUM_ENCODED_BYTES,
    level: int = DEFAULT_LEVEL,
) -> tuple[bytes, bool]:
    """Return the body to send and whether it was gzipped."""
    if len(raw) < minimum_bytes:
        return raw, False
    if not is_compressible(content_type):
        return raw, False
    if not accepts_gzip(accept_encoding):
        return raw, False
    return gzip.compress(raw, compresslevel=level), True


def encoding_headers(encoded: bool) -> dict[str, str]:
    """Headers that must accompany a compressed (or compressible) body."""
    if not encoded:
        return {}
    return {"Content-Encoding": "gzip", "Vary": "Accept-Encoding"}


__all__ = [
    "DEFAULT_LEVEL",
    "MINIMUM_ENCODED_BYTES",
    "accepts_gzip",
    "encode_body",
    "encoding_headers",
    "is_compressible",
    "request_accept_encoding",
]
