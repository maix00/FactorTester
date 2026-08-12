"""Shared HTTP response adapters for the Manager."""

from __future__ import annotations

import json
from typing import Any


def json_response(
    handler: Any,
    payload: dict[str, Any],
    status: int = 200,
    *,
    headers: dict[str, str] | None = None,
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
        handler.send_header(key, value)
    if "Set-Cookie" not in response_headers:
        token = getattr(handler, "_bearer_token", lambda: "")()
        state = getattr(handler, "state", None)
        if token and state is not None and state.session(token) is not None:
            handler.send_header("Set-Cookie", handler._session_cookie(token))
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
