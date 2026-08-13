"""Small HTTP response helpers for the 7997 data plane."""

from __future__ import annotations

import json


def json_error(
    handler,
    status: int,
    message: str,
    *,
    code: str = "transfer_error",
) -> None:
    body = json.dumps(
        {"success": False, "error": {"code": code, "message": str(message)}},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(body)


def empty_response(handler, status: int) -> None:
    handler.send_response(status)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", "0")
    handler.end_headers()
