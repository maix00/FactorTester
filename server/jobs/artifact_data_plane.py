"""Shared protocol helpers for the per-server artifact data plane.

Control-plane requests are authenticated by the Manager/service session.  A
download is intentionally a separate short-lived capability: the 7998
control plane signs a ticket and the 7997 data plane verifies it before
reading the local retained file.  No user session or SQLite write is needed
on the data-plane request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

import settings as Settings


ARTIFACT_DATA_SCHEMA_VERSION = 1
DEFAULT_ARTIFACT_DATA_PORT = 7997
DEFAULT_TICKET_TTL_SECONDS = 15 * 60
MAX_TICKET_TTL_SECONDS = 60 * 60
_TICKET_SECRET_ENV = "GTHT_ARTIFACT_TICKET_SECRET"
_TICKET_SECRET_FILE_ENV = "GTHT_ARTIFACT_TICKET_SECRET_FILE"


class ArtifactTicketError(ValueError):
    """Raised when a data-plane ticket is malformed or not authorized."""


def artifact_data_port(value: object | None = None) -> int:
    """Return the configured data-plane port, defaulting to 7997."""
    raw = value
    if raw in (None, ""):
        raw = os.environ.get(
            "FACTORTESTER_ARTIFACT_DATA_PORT",
            os.environ.get("GTHT_ARTIFACT_DATA_PORT", DEFAULT_ARTIFACT_DATA_PORT),
        )
    try:
        port = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("artifact data port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("artifact data port must be between 1 and 65535")
    return port


def _secret_file() -> Path:
    configured = str(os.environ.get(_TICKET_SECRET_FILE_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(Settings.CACHE_DIR) / "runtime" / "artifact-data-ticket.key").resolve()


def ticket_secret() -> bytes:
    """Load the shared ticket key, creating a private local key if needed."""
    configured = str(os.environ.get(_TICKET_SECRET_ENV) or "").strip()
    if configured:
        return configured.encode("utf-8")
    path = _secret_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return path.read_bytes()
    except FileNotFoundError:
        value = secrets.token_bytes(32)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return path.read_bytes()
        try:
            os.write(fd, value)
        finally:
            os.close(fd)
        return value


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ArtifactTicketError("invalid artifact ticket encoding") from exc


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class ArtifactTicketCodec:
    """HMAC-signed, short-lived capability tokens for one artifact."""

    def __init__(self, secret: bytes | str | None = None) -> None:
        if secret is None:
            secret = ticket_secret()
        self.secret = (
            secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
        )
        if len(self.secret) < 16:
            raise ValueError("artifact ticket secret must be at least 16 bytes")

    def issue(
        self,
        *,
        owner: str,
        job_id: str,
        name: str,
        server_id: str = "",
        preview: bool = False,
        ttl_seconds: int | float = DEFAULT_TICKET_TTL_SECONDS,
        now: int | float | None = None,
    ) -> str:
        issued_at = int(time.time() if now is None else now)
        ttl = max(1, min(MAX_TICKET_TTL_SECONDS, int(ttl_seconds)))
        payload: dict[str, Any] = {
            "v": ARTIFACT_DATA_SCHEMA_VERSION,
            "owner": str(owner),
            "job_id": str(job_id),
            "name": str(name),
            "server_id": str(server_id or ""),
            "preview": bool(preview),
            "iat": issued_at,
            "exp": issued_at + ttl,
            "nonce": secrets.token_urlsafe(12),
        }
        encoded = _b64(_canonical_json(payload))
        signature = _b64(hmac.new(
            self.secret,
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest())
        return f"{encoded}.{signature}"

    def verify(
        self,
        token: str,
        *,
        owner: str = "",
        job_id: str = "",
        name: str = "",
        server_id: str = "",
        now: int | float | None = None,
    ) -> dict[str, Any]:
        encoded, separator, supplied_signature = str(token or "").partition(".")
        if not separator or not encoded or not supplied_signature:
            raise ArtifactTicketError("invalid artifact ticket")
        expected_signature = _b64(hmac.new(
            self.secret,
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest())
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ArtifactTicketError("invalid artifact ticket signature")
        try:
            payload = json.loads(_unb64(encoded).decode("utf-8"))
        except (UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ArtifactTicketError("invalid artifact ticket payload") from exc
        if not isinstance(payload, dict) or payload.get("v") != ARTIFACT_DATA_SCHEMA_VERSION:
            raise ArtifactTicketError("unsupported artifact ticket")
        try:
            expires_at = int(payload["exp"])
            issued_at = int(payload["iat"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ArtifactTicketError("invalid artifact ticket lifetime") from exc
        current = int(time.time() if now is None else now)
        if expires_at <= current or issued_at > current + 30:
            raise ArtifactTicketError("artifact ticket expired")
        for key, expected in (
            ("owner", owner),
            ("job_id", job_id),
            ("name", name),
            ("server_id", server_id),
        ):
            if expected and not hmac.compare_digest(
                str(payload.get(key) or ""), str(expected),
            ):
                raise ArtifactTicketError("artifact ticket target mismatch")
        return dict(payload)


def artifact_data_endpoint(
    *,
    endpoint: str | None = None,
    port: int | None = None,
    default_endpoint: str = "http://127.0.0.1:7998",
) -> str:
    """Resolve the public URL of this host's 7997 data service."""
    configured = str(
        endpoint
        or os.environ.get("FACTORTESTER_ARTIFACT_DATA_ENDPOINT")
        or ""
    ).strip().rstrip("/")
    selected_port = artifact_data_port(port)
    if configured:
        parsed = urlparse(configured)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("artifact data endpoint must be an http or https URL")
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return urlunparse((
            parsed.scheme,
            f"{host}:{selected_port}",
            "",
            "",
            "",
            "",
        )).rstrip("/")
    parsed = urlparse(str(default_endpoint).strip())
    scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "http"
    host = parsed.hostname or "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{scheme}://{host}:{selected_port}"


def artifact_data_url(
    endpoint: str,
    *,
    job_id: str,
    name: str,
    ticket: str,
) -> str:
    path_name = "archive" if str(name) == "__archive__" else str(name)
    return (
        f"{str(endpoint).rstrip('/')}/v1/artifacts/"
        f"{quote(str(job_id), safe='')}/{quote(path_name, safe='')}"
        f"?ticket={quote(str(ticket), safe='')}"
    )
