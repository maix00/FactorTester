"""Verified outbound transport shared by Manager federation clients."""

from __future__ import annotations

import os
import ssl
from pathlib import Path
from typing import Mapping
from urllib.request import Request, urlopen


FEDERATION_CA_FILE_ENV = "FACTORTESTER_FEDERATION_CA_FILE"


def federation_ca_file(
    value: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """Resolve an optional private-CA bundle without weakening verification."""
    values = os.environ if environ is None else environ
    configured = str(
        value if value is not None else values.get(FEDERATION_CA_FILE_ENV, "")
    ).strip()
    if not configured:
        return None
    path = Path(configured).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"federation CA file was not found: {path}")
    return path


class FederationTransport:
    """Open HTTP(S) peer requests with system roots plus an optional private CA."""

    def __init__(self, *, ca_file: str | Path | None = None) -> None:
        configured = federation_ca_file(ca_file)
        self.ca_file = configured
        self.ssl_context: ssl.SSLContext | None = None
        if configured is not None:
            context = ssl.create_default_context()
            context.load_verify_locations(cafile=str(configured))
            self.ssl_context = context

    def open(self, request: Request, *, timeout: float):
        if self.ssl_context is None:
            return urlopen(request, timeout=timeout)
        return urlopen(
            request,
            timeout=timeout,
            context=self.ssl_context,
        )
