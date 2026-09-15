"""Shared HTTP response adapters for the Manager."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, TypeAlias
from urllib.parse import quote


HeaderValue: TypeAlias = str | list[str] | tuple[str, ...]


def download_response(
    handler: Any,
    raw: bytes,
    content_type: str,
    filename: str,
    *,
    disposition: str = "attachment",
) -> None:
    """Write a downloadable body, keeping the real name of a CJK file.

    The ASCII fallback stays for older clients; the RFC 5987 form carries the
    original title so a Chinese report downloads under its own name.
    """
    safe_filename = re.sub(
        r"[^A-Za-z0-9._-]", "_", Path(filename).name,
    ) or "research-object"
    header = f'{disposition}; filename="{safe_filename}"'
    if safe_filename != Path(filename).name:
        header += f"; filename*=UTF-8''{quote(Path(filename).name, safe='')}"
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Disposition", header)
    handler.send_header("Cache-Control", "private, no-cache")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def json_response(
    handler: Any,
    payload: dict[str, Any],
    status: int = 200,
    *,
    headers: dict[str, HeaderValue] | None = None,
) -> None:
    """Write a JSON response while preserving Manager session refreshes.

    The handler is intentionally duck-typed.  This keeps the response seam
    independent from ``runtime.Handler`` and allows route adapters to be
    tested with a small fake handler.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    response_headers = headers or {}
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    for key, value in response_headers.items():
        if isinstance(value, (list, tuple)):
            for item in value:
                handler.send_header(key, str(item))
        else:
            handler.send_header(key, value)
    if "Set-Cookie" not in response_headers:
        token = getattr(handler, "_bearer_token", lambda: "")()
        state = getattr(handler, "state", None)
        if token and state is not None and state.session(token) is not None:
            handler.send_header("Set-Cookie", handler._session_cookie(token))
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
