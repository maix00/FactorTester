"""Cookie-free reads from a short-lived FactorTester data-plane capability."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .http import BinaryResponse, HttpClientError


class _RejectRedirects(HTTPRedirectHandler):
    """Never forward a bearer capability to a redirected origin."""

    def redirect_request(self, request, file_pointer, code, message, headers, url):
        del request, file_pointer, code, message, headers, url
        return None


def download_capability(
    access: dict[str, Any],
    *,
    timeout: float,
    maximum_bytes: int,
    expected_sha256: str = "",
    content_type: str = "application/octet-stream",
    tls_context=None,
) -> BinaryResponse:
    """Read one authorized 7997 object without exposing Manager cookies."""

    url, bearer, expected_size = _validated_access(access)
    if maximum_bytes <= 0:
        raise ValueError("binary download limit must be positive")
    if expected_size > maximum_bytes:
        raise ValueError("artifact exceeds local download limit")
    request = _request(url, bearer)
    try:
        with build_opener(_RejectRedirects(), *([HTTPSHandler(context=tls_context)] if tls_context else [])).open(
            request, timeout=max(1.0, float(timeout)),
        ) as response:
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) != expected_size:
                raise ValueError("artifact size does not match transfer capability")
            raw = response.read(maximum_bytes + 1)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HttpClientError(exc.code, url, body) from exc
    if len(raw) > maximum_bytes:
        raise ValueError("artifact exceeds local download limit")
    if len(raw) != expected_size:
        raise ValueError("artifact size does not match transfer capability")
    digest = str(expected_sha256 or "").strip().lower()
    if digest and hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("artifact SHA-256 does not match transfer capability")
    return BinaryResponse(
        content=raw,
        content_type=str(content_type or "application/octet-stream"),
    )


def download_capability_to_path(
    access: dict[str, Any],
    destination: str | Path,
    *,
    timeout: float,
    expected_sha256: str,
    content_type: str = "application/octet-stream",
    tls_context=None,
) -> dict[str, Any]:
    """Stream a capability to an atomic local file and verify its digest."""

    url, bearer, expected_size = _validated_access(access)
    digest = str(expected_sha256 or "").strip().lower()
    if len(digest) != 64 or any(value not in "0123456789abcdef" for value in digest):
        raise ValueError("artifact SHA-256 metadata is invalid")
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.part")
    request = _request(url, bearer)
    written = 0
    hasher = hashlib.sha256()
    try:
        with build_opener(_RejectRedirects(), *([HTTPSHandler(context=tls_context)] if tls_context else [])).open(
            request, timeout=max(1.0, float(timeout)),
        ) as response, staging.open("wb") as output:
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) != expected_size:
                raise ValueError("artifact size does not match transfer capability")
            while chunk := response.read(1024 * 1024):
                written += len(chunk)
                if written > expected_size:
                    raise ValueError("artifact size does not match transfer capability")
                hasher.update(chunk)
                output.write(chunk)
        if written != expected_size:
            raise ValueError("artifact size does not match transfer capability")
        actual_sha256 = hasher.hexdigest()
        if actual_sha256 != digest:
            raise ValueError("artifact SHA-256 does not match transfer capability")
        staging.replace(target)
    except HTTPError as exc:
        staging.unlink(missing_ok=True)
        body = exc.read().decode("utf-8", errors="replace")
        raise HttpClientError(exc.code, url, body) from exc
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    return {
        "path": str(target),
        "size_bytes": written,
        "content_hash": actual_sha256,
        "content_type": str(content_type or "application/octet-stream"),
    }


def _validated_access(access: dict[str, Any]) -> tuple[str, str, int]:
    url = str(access.get("url") or "").strip()
    bearer = str(access.get("bearer") or "").strip()
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("transfer capability URL is invalid")
    if not bearer:
        raise ValueError("transfer capability bearer is missing")
    try:
        expected_size = int(access.get("expected_size"))
    except (TypeError, ValueError) as exc:
        raise ValueError("transfer capability size is invalid") from exc
    if expected_size < 0:
        raise ValueError("transfer capability size is invalid")
    return url, bearer, expected_size


def _request(url: str, bearer: str) -> Request:
    return Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "Authorization": f"Bearer {bearer}",
            "User-Agent": "FactorTester-CLI/1",
            "X-FactorTester-Client": "cli-data-plane",
        },
        method="GET",
    )


__all__ = ["download_capability", "download_capability_to_path"]
