"""Manager-internal access to its own client-facing data-plane listener."""

from __future__ import annotations

import os
import ssl
from urllib.parse import urlsplit, urlunsplit


def loopback_client_access(
    public_url: object,
) -> tuple[str, ssl.SSLContext | None]:
    """Return a loopback URL and TLS context for one local client ticket."""
    selected = str(public_url or "")
    parsed = urlsplit(selected)
    if parsed.scheme not in {"http", "https"} or parsed.port is None:
        return selected, None
    host = "localhost" if parsed.scheme == "https" else "127.0.0.1"
    internal_url = urlunsplit((
        parsed.scheme, f"{host}:{parsed.port}", parsed.path,
        parsed.query, parsed.fragment,
    ))
    if parsed.scheme != "https":
        return internal_url, None
    certificate = str(
        os.environ.get("FACTORTESTER_ARTIFACT_TLS_CERT")
        or os.environ.get("FACTORTESTER_MANAGER_TLS_CERT")
        or ""
    ).strip()
    if not certificate:
        return selected, None
    return internal_url, ssl.create_default_context(cafile=certificate)


__all__ = ["loopback_client_access"]
