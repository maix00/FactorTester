"""Small helpers for optional TLS on Manager and client transfer surfaces."""

from __future__ import annotations

import os
import ssl
from pathlib import Path


def configured_tls_paths(
    certificate: str | None = None,
    private_key: str | None = None,
    *,
    certificate_env: str,
    private_key_env: str,
) -> tuple[Path, Path] | None:
    """Return a complete certificate/key pair or ``None`` when TLS is off."""
    cert_value = str(
        certificate if certificate is not None else os.environ.get(certificate_env, "")
    ).strip()
    key_value = str(
        private_key if private_key is not None else os.environ.get(private_key_env, "")
    ).strip()
    if not cert_value and not key_value:
        return None
    if not cert_value or not key_value:
        raise ValueError(
            f"{certificate_env} and {private_key_env} must be configured together"
        )
    cert_path = Path(cert_value).expanduser().resolve()
    key_path = Path(key_value).expanduser().resolve()
    if not cert_path.is_file():
        raise FileNotFoundError(f"TLS certificate was not found: {cert_path}")
    if not key_path.is_file():
        raise FileNotFoundError(f"TLS private key was not found: {key_path}")
    return cert_path, key_path


def server_tls_context(certificate: Path, private_key: Path) -> ssl.SSLContext:
    """Build a TLS 1.2+ server context for an already-bound HTTP server."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(
        certfile=str(certificate),
        keyfile=str(private_key),
    )
    return context


def enable_server_tls(
    server: object,
    context: ssl.SSLContext,
    *,
    allow_plain_http: bool = False,
) -> None:
    """Enable TLS, optionally retaining HTTP only for an HTTPS redirect."""
    if allow_plain_http:
        # The Manager handler negotiates each accepted connection inside its
        # worker thread.  Keeping the listener itself unwrapped prevents one
        # idle or malformed TLS client from blocking every subsequent accept.
        server.tls_context = context
    else:
        server.socket = context.wrap_socket(server.socket, server_side=True)
    server.tls_enabled = True
    server.tls_accepts_plain_http = allow_plain_http
